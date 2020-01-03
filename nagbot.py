#!/usr/bin/env python3

import pprint
import telegram.bot
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove)
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, ConversationHandler)
from telegram.ext import messagequeue as mq
from telegram.utils.request import Request


import logging
import time
import uuid

import os, sys, logging, time, pprint, warnings, argparse, re, configparser, string, subprocess, uuid, types

maxMessageSize = 4096
maxPluginOutputMessages = 5
warnings.filterwarnings('ignore')
ME = os.path.basename(sys.argv[0])
loggingFormat='%(asctime)s %(filename)s: %(message)s'
#logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format=loggingFormat)
#logger = logging.getLogger(ME)
logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s',
     level=logging.DEBUG)
logger = logging.getLogger()
start_time = time.time()
configMain = {}
config = {}
notificationSubscriptions = {}

configFileHelp = \
"""

Configuration File Format
=========================

Configuration takes the form of a "ini" style file.  All 
values live in [config] section

INI File Values
===============

[config]
TOKEN   - Telegram Token provided by the botFather (App praise be upon you sir)
DADUSER - Who is your daddy to report issues to, numeric Telegram ID
DATADIR - The base of the bot data directory
PLUGINDIRS  - One or more additional plugin directories, One directory per line.

"""

parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=configFileHelp)
parser.add_argument("-v", "--verbose",  help="increase output verbosity", action="store_true")
parser.add_argument("-d", "--debug",    help="enable debugging output", action="store_true")
parser.add_argument("configFile",    help="provide a ini configuration file", action="store")
args = parser.parse_args()

if args.verbose:
    logger.setLevel(logging.INFO)
if args.debug:
    logger.setLevel(logging.DEBUG)

def bomb(chunk):
    logger.error("BOMB: %s",chunk)
    sys.exit(1)


configMain = configparser.ConfigParser()

try:
    logger.debug("Reading configFile [{}]".format(args.configFile))
    configMain.read_file(open(args.configFile))
except Exception as error:
    bomb("Unable to read configFile [{}]".format(error))

##############
# Bot Settings
##############
try:
    config = configMain['config']  # just the config section
except Exception as error:
    bomb("Unable to find configFile section [config], error: [{}]".format(error))

try: 
    botToken = config['TOKEN'] 
    dadUserId = config['DADUSER'] 
    dataDir = config['DATADIR'] 
except Exception as error:
    bomb("Unable to find required config values in configFile, error: [{}]".format(error))

logger.debug("Config Values: botToken[{}] dadUserId[{}] dataDir[{}]".format(botToken,dadUserId,dataDir))

if not os.path.exists(dataDir):
    bomb("DATADIR [{}] does not exist".format(dataDir))
notificationDir = os.path.join(dataDir, "notifications")
if not os.path.exists(notificationDir):
    os.mkdir(notificationDir)
seenUserDir = os.path.join(dataDir, "seen")
if not os.path.exists(seenUserDir):
    os.mkdir(seenUserDir)
allowedUserDir = os.path.join(dataDir, "allowed")
if not os.path.exists(allowedUserDir):
    os.mkdir(allowedUserDir)
pluginDirs = []
pluginDirs.append(os.path.join(dataDir,"plugins"))
if config.get('PLUGINDIRS',None):
    for eachDir in config['PLUGINDIRS'].splitlines():
        if os.path.exists(eachDir):
            pluginDirs.append(eachDir)

##########################################################################################
# Below is used to decorate send_message to use messagequeue, as per:
# https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits
##########################################################################################
class MQBot(telegram.bot.Bot):
    '''A subclass of Bot which delegates send method handling to MQ'''
    def __init__(self, *args, is_queued_def=True, mqueue=None, **kwargs):
        super(MQBot, self).__init__(*args, **kwargs)
        # below 2 attributes should be provided for decorator usage
        self._is_messages_queued_default = is_queued_def
        self._msg_queue = mqueue or mq.MessageQueue()

    def __del__(self):
        try:
            self._msg_queue.stop()
        except:
            pass

    @mq.queuedmessage
    def send_message(self, *args, **kwargs):
        '''Wrapped method would accept new `queued` and `isgroup`
        OPTIONAL arguments'''
        return super(MQBot, self).send_message(*args, **kwargs)




#                             # for test purposes limit global throughput to 3 messages per 3 seconds
messQueue = mq.MessageQueue() #all_burst_limit=3, all_time_limit_ms=3000)
# set connection pool size for bot 
request = Request(con_pool_size=8)
# Create bot.ext object from decorated class created
# above which includes message queuing 
myBot = MQBot(botToken, request=request, mqueue=messQueue)

updater = Updater(bot=myBot, use_context=True)
dispatcher = updater.dispatcher
jobs = updater.job_queue 








def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I am {} bot, I am not a human. \nYou are a human (presumably)\nYour chatId is {}, and your Username is {}.  \nThank you.".format(ME,update.effective_chat.id,update.effective_chat.username))
    if not quickDenyCheck(update,context): return

def echo(update, context):
    if not quickDenyCheck(update,context): return
    context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

def yell(update, context): 
    if not quickDenyCheck(update,context): return
    yell_text = "*yelling* {}".format(' '.join(context.args).upper())
    context.bot.send_message(chat_id=update.effective_chat.id, text=yell_text)

def findPlugin(command):
    for pluginDir in pluginDirs:
        p = os.path.join(pluginDir,command)
        if os.path.isfile(p) and os.access(p, os.X_OK):  #gotcha, 
            logger.debug("Found plugin [{}] for command[{}]".format(p,command))
            return(p)
    logger.debug("No plugin for command[{}]".format(command))
    return(None)

def unknown(update, context):
    if not quickDenyCheck(update,context): return
    unknownCommand = update.message.text.strip().split()[0] # Only the command please
    if unknownCommand.startswith("/"): unknownCommand = unknownCommand.split("/")[1] # Chop off slash, only take first word, tricky
    # Check for plugins in plugins dir
    pluginExe = findPlugin(unknownCommand)
    args = []
    if not pluginExe == None:
        args.append(pluginExe)
        if context.args: args.extend(context.args)
        logger.info("Plugin Command: [{}]".format("],[".join(args)))
    else:
        logger.info("No plugin found for unknownCommand[{}]".format(unknownCommand))
        context.bot.send_message(chat_id=update.effective_chat.id, text="Unknown Command [{}]".format(unknownCommand))
        return()
    # I am not happy with below... really need to have a timeout here
    with subprocess.Popen(args, shell=False, bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
        output=""
        totalMessageCount=0
        for line in proc.stdout:
            line = line.decode()
            if len(output) + len(line) > maxMessageSize:
                # Would be Too big, Ship it
                context.bot.send_message(chat_id=update.effective_chat.id, text=output)
                output=""  # clear buff
                totalMessageCount+=1
                if totalMessageCount >= maxPluginOutputMessages:
                    # No more. 
                    break
            output += line # append
        if output: 
            context.bot.send_message(chat_id=update.effective_chat.id, text=output)

def info(update, context):
    if not quickDenyCheck(update,context): return
    infoText = "INFO: update.effective_chat.id[{}]  update.effective_chat.username[{}], full debug dump logged".format(update.effective_chat.id,update.effective_chat.username)
    context.bot.send_message(chat_id=update.effective_chat.id, text=infoText)
    logging.info("INFO: update = {}".format(pprint.pformat(update)))
    logging.info("INFO: context = {}".format(pprint.pformat(context)))
    #context.bot.send_message(chat_id=update.effective_chat.id, text="INFO: update = {}".format(repr(update)))
    #context.bot.send_message(chat_id=update.effective_chat.id, text="INFO: context = {}".format(repr(context)))

def setCommand(update, context):
    if not quickDenyCheck(update,context): return
    reply_keyboard = [['/info', 'Blah', 'Ok Boomer', 'Please stop talking']]
    update.message.reply_text(
        'Hello, Below is a test reply keyboard...?',
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))

set_handler = CommandHandler('set', setCommand)
dispatcher.add_handler(set_handler)

echo_handler = MessageHandler(Filters.text, echo)
start_handler = CommandHandler('start', start)
yell_handler = CommandHandler('yell', yell)
info_handler = CommandHandler('info', info)
unknown_handler = MessageHandler(Filters.command, unknown)

dispatcher.add_handler(echo_handler)
dispatcher.add_handler(start_handler)
dispatcher.add_handler(yell_handler)
dispatcher.add_handler(info_handler)
dispatcher.add_handler(unknown_handler) # ALways last

updater.start_polling()

def quickDenyCheck(update,context):
    seenUser(update.effective_chat)   # effective chat is diff from eff user when in group context
    seenUser(update.effective_user)   # we want to validate both groups and users (i think)
    if isUserAllowed(update.effective_chat):   # Check auth for chat (groups etc)
        return(True)
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, {}. We are not acquainted. There is nothing else you can do here.".format(update.effective_chat.username))
        return(False)
    if isUserAllowed(update.effective_user):    # Check auth for user
        return(True)
    else:
        context.bot.send_message(chat_id=update.effective_user.id, text="Hello, {}. We are not acquainted. There is nothing else you can do here.".format(update.effective_user.username))
        return(False)

def touchFile(fileName,content=None):
    logger.debug("Touching fileName[{}] content=[{}]".format(fileName,content))
    if not content:
        open(fileName, 'a').close()   # Simple touch, no truncate
    else:
        with open(fileName, 'w') as f:
            f.write(content)

def userTouchFile(chatId,username):
    return("user.{}.{}".format(username,chatId))

def dumpo(obj):
    o=""
    for attr in dir(obj):
        if hasattr( obj, attr ) and type(getattr(obj, attr)) != types.MethodType:  # Only non-methods
            o += "%s = %s (%s)\n" % (attr, getattr(obj, attr),type(getattr(obj, attr)))
    return(o)

def seenUser(user):
    chatId = user.id
    username = user.username
    logger.debug("Seen user: chatId[{}] username[{}]".format(chatId,username))
    f = os.path.join(seenUserDir,userTouchFile(chatId,username))
    c = str(dumpo(user))
    touchFile(f,content=c)

def isUserAllowed(user):
    chatId = user.id
    username = user.username
    f = os.path.join(allowedUserDir,userTouchFile(chatId,username))
    if os.path.exists(f):
        logger.debug("Allowed user: chatId[{}] username[{}] f[{}]".format(chatId,username,f))
        return(True)
    else:
        logger.debug("Denied user: chatId[{}] username[{}] f[{}]".format(chatId,username,f))
        return(False)

def checkNotificationQueue(processFiles=True):
    logger.debug("Checking Notification Queue")
    with os.scandir(notificationDir) as notificationDirFiles:
        for notificationDirFile in notificationDirFiles:
            if notificationDirFile.is_dir():   # Subdirs are topics
                logger.debug("Checking Notification Queue, Dir[{}]".format(notificationDirFile.path))
                with os.scandir(notificationDirFile) as notificationFiles:
                    notificationTopic = os.path.basename(notificationDirFile)
                    notificationSubsFile  = "{}.subs.txt".format(notificationDirFile.path)
                    logger.debug("Checking Notification Queue, Topic[{}] Dir[{}] notificationSubsFile[{}]".format(notificationTopic,notificationDirFile.path,notificationSubsFile))
                    notificationSubscriptions[notificationTopic]=[]   # Initial value, empty list
                    if os.path.exists(notificationSubsFile):
                        with open(notificationSubsFile) as file:
                            for line in file:
                                line=line.strip()
                                if line.startswith("#"): continue   # Skip all full line comments
                                thisId = line.split("#")[0]   # We only look at the first word or anything before a #comment
                                thisId = thisId.split(" ")[0] # We only look at the first word or anything before a #comment
                                notificationSubscriptions[notificationTopic].append(thisId)
                                logger.debug("Append thisId[{}] to topic[{}] subscription".format(thisId,notificationTopic))
                    else:
                        open(notificationSubsFile, 'a').close()   # If not exist, create a template
                        logger.debug("Created empty notificationSubsFile[{}]".format(notificationSubsFile))

                    for notificationFile in notificationFiles:
                        if notificationFile.is_file():
                            if processFiles:
                                processNotificationFile(notificationTopic,notificationFile)

def processNotificationFile(topic,notificationFile):
    notText = ""
    doneDir = os.path.join(os.path.dirname(notificationFile), "done")
    filebase = os.path.basename(notificationFile)
    if not os.path.exists(doneDir): 
        logger.debug("Creating doneDir[{}]".format(doneDir))
        os.mkdir(doneDir)
    notificationFileProcessed = os.path.join(doneDir,"{}.{}".format(filebase,str(uuid.uuid1())))
    os.rename(notificationFile,notificationFileProcessed)
    with open(notificationFileProcessed) as file:
        notText = file.read().strip()
    logger.info("Processing topic[{}] file[{}] content[{}]".format(topic,notificationFileProcessed,notText))
    for subId in notificationSubscriptions[topic]:
        logger.info("Sending to subId[{}]".format(subId))
        dispatcher.bot.send_message(chat_id=subId,text="{} ({})".format(notText,topic))


# debug job_minute = jobs.run_repeating(callback_minute, interval=60, first=0)
jobNotificationQueue = jobs.run_repeating(checkNotificationQueue, interval=5, first=0)

# Startup stuff
checkNotificationQueue(processFiles=False)  # Just populate topic names

#dispatcher.bot.send_message(chat_id=dadUserId, text="Hello, Main loop, {} STARTUP time={}".format(ME,time.asctime()))

while(True):
    #dispatcher.bot.send_message(chat_id=dadUserId, text="Hello, Main loop, I am still alive. time={}".format(time.asctime()))
    print("Sleep...")
    time.sleep(90)
