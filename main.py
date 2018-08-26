#!/usr/bin/python3

import praw
import os
import logging.handlers
import sys
import signal
import time
import traceback
import sqlite3
import re
from datetime import datetime
from datetime import timedelta

### Config ###
LOG_FOLDER_NAME = "logs"
SUBREDDIT = "3atatime"
USER_AGENT = "story aggregator (by /u/Watchful1)"
LOOP_TIME = 5 * 60
REDDIT_OWNER = "Watchful1"
SUBREDDIT_LINK = "https://www.reddit.com/r/{}/comments/".format(SUBREDDIT)
DATABASE_NAME = "database.db"
BACKLOG_HOURS = 0
START_TIME = datetime.utcnow()
TRIGGER = "the end"
SCORE = 7

### Logging setup ###
LOG_LEVEL = logging.DEBUG
if not os.path.exists(LOG_FOLDER_NAME):
	os.makedirs(LOG_FOLDER_NAME)
LOG_FILENAME = LOG_FOLDER_NAME+"/"+"bot.log"
LOG_FILE_BACKUPCOUNT = 5
LOG_FILE_MAXSIZE = 1024 * 256 * 64

log = logging.getLogger("bot")
log.setLevel(LOG_LEVEL)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
log_stderrHandler = logging.StreamHandler()
log_stderrHandler.setFormatter(log_formatter)
log.addHandler(log_stderrHandler)
if LOG_FILENAME is not None:
	log_fileHandler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=LOG_FILE_MAXSIZE, backupCount=LOG_FILE_BACKUPCOUNT)
	log_formatter_file = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	log_fileHandler.setFormatter(log_formatter_file)
	log.addHandler(log_fileHandler)


def signal_handler(signal, frame):
	log.info("Handling interupt")
	dbConn.commit()
	dbConn.close()
	sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


dbConn = sqlite3.connect(DATABASE_NAME)
c = dbConn.cursor()
c.execute('''
	CREATE TABLE IF NOT EXISTS endComments (
		ID INTEGER PRIMARY KEY AUTOINCREMENT,
		CommentID VARCHAR(10) NOT NULL,
		ThreadID VARCHAR(10) NOT NULL,
		Created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
		UNIQUE (CommentID)
	)
''')
dbConn.commit()


def addComment(commentID, threadID):
	c = dbConn.cursor()
	try:
		c.execute('''
			INSERT INTO endComments
			(CommentID, ThreadID)
			VALUES (?, ?, ?)
		''', (commentID, threadID))
	except sqlite3.IntegrityError:
		return False

	dbConn.commit()
	return True


def getComments():
	c = dbConn.cursor()
	results = []
	for row in c.execute('''
		SELECT CommentID
		FROM endComments
		ORDER BY Created DESC
		'''):
		results.append('t1_'+row[0])

	return results


def endThread(threadID):
	c = dbConn.cursor()
	c.execute('''
		DELETE FROM endComments
		WHERE ThreadID = ?
	''', (threadID,))
	dbConn.commit()

	if c.rowcount == 1:
		return True
	else:
		return False


def deleteOldThreads():
	c = dbConn.cursor()
	c.execute('''
		DELETE FROM endComments
		WHERE Created < datetime('now', '-7 days')
	''')
	dbConn.commit()

	if c.rowcount > 0:
		return True
	else:
		return False


def getIDFromFullname(fullname):
	return re.findall('^(?:t\d_)?(.{4,8})', fullname)[0]


user = None
if len(sys.argv) >= 2:
	user = sys.argv[1]
else:
	log.error("No user specified, aborting")
	sys.exit(0)

log.debug("Connecting to reddit")


r = praw.Reddit(
	user
	,user_agent=USER_AGENT)


log.info("Logged into reddit as /u/{}".format(str(r.user.me())))

while True:
	try:
		sub = r.subreddit(SUBREDDIT)
		for comment in sub.stream.comments():
			if comment is None or datetime.utcfromtimestamp(comment.created_utc) < START_TIME - timedelta(hours=BACKLOG_HOURS) \
					or comment.author == r.user.me():
				continue

			log.info("Processing comment {} from /u/{}".format(comment.id, comment.author.name))
			body = comment.body.lower()
			if "the end" in body:
				log.info("Found trigger")
				if not comment.submission.saved:
					log.info("Submission not saved, adding comment to database")
					addComment(comment.id, getIDFromFullname(comment.link_id))

			for commentCheck in r.info(getComments()):
				checkedSubmissions = set()
				if commentCheck.score >= SCORE and commentCheck.submission.id not in checkedSubmissions:
					log.debug("Comment {} over threshold at {}".format(commentCheck.id, commentCheck.score))
					story = []
					parent = commentCheck
					while True:
						parent = parent.parent
						if parent.parent_id.startswith("t3"):
							log.debug("Hit submission, breaking")
							break
						log.debug("Adding body of {}".format(parent.id))
						story.append(parent.body)

					resultStory = ' '.join(reversed(story))

					resultComment = commentCheck.submission.reply(resultStory)
					log.debug("Submission {} ended, result comment {}".format(commentCheck.submission.id, resultComment.id))
					# resultComment.mod.distinguish(how='yes', sticky=True)
					commentCheck.submission.save()
					endThread(commentCheck.submission.id)
					checkedSubmissions.add(commentCheck.submission.id)

			deleteOldThreads()
	except Exception as err:
		log.warning("Hit an error in main loop")
		log.warning(traceback.format_exc())

	time.sleep(LOOP_TIME)
