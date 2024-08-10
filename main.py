#!/usr/bin/python3
import os
import re
import json
import time
import logging
import asyncio
import datetime
import functools
import traceback
import threading

from uuid import uuid4

import mailparser

import tornado.web
import tornado.ioloop

from tornado.web import HTTPError
from tornado.options import define, options

from peewee import *
from playhouse.shortcuts import model_to_dict

import aiosmtpd.smtp
from aiosmtpd.controller import Controller


database = SqliteDatabase(None)

# 从配置文件加载邮箱后缀列表
def load_email_domains():
    with open('config.json') as config_file:
        config = json.load(config_file)
        return config.get('emailDomains', [])

# 全局邮箱后缀列表
email_domains = load_email_domains()

class BaseModel(Model):
    class Meta:
        database = database

    def to_dict(self, **kwargs):
        ret = model_to_dict(self, **kwargs)
        return ret


class User(BaseModel):
    def dict(self):
        fmt = "%Y-%m-%d %H:%M:%S"
        item = self.to_dict(exclude=[User.mail, User.create_time])
        return item

    uuid = CharField(max_length=32, unique=True)
    create_time = DateTimeField(default=datetime.datetime.now)
    last_active = BigIntegerField(default=time.time)


class Mail(BaseModel):
    def dict(self, exclude=[]):
        fmt = "%Y-%m-%d %H:%M:%S"
        item = self.to_dict(exclude=[Mail.user, *exclude])
        item["create_time"] = self.create_time.strftime(fmt)
        item["send_time"] = self.send_time.strftime(fmt)
        return item

    user = ForeignKeyField(User, backref="mail")

    subject = CharField(max_length=512)
    content = CharField(max_length=65535)
    html_content = CharField(max_length=65535)
    sender = CharField(max_length=256)

    create_time = DateTimeField(default=datetime.datetime.now)
    send_time = DateTimeField()


class SmtpdHandler(object):
    domains = email_domains

    async def handle_DATA(self, server, session, envelope):
        mail = mailparser.parse_from_bytes(envelope.content)
        mm = dict(subject=mail.subject)
        mm["content"] = "".join(mail.text_plain)
        mm["html_content"] = "".join(mail.text_html)
        mm["sender"] = envelope.mail_from
        mm["send_time"] = mail.date

        Mail.create(**mm, user=envelope.rcpt_tos[0])
        return "250 Message accepted for delivery"

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        addr = re.search("^(?P<uuid>[^@]+)@(?P<domain>[a-z0-9_\.-]+)$", address)
        if addr is None:
            return "501 Malformed Address"
        if addr["domain"] not in self.domains:
            return "501 Domain Not Handled"
        user = User.get_or_none(uuid=addr["uuid"])
        if user is None:
            return "510 Address Does Not Exist"
        envelope.rcpt_tos.append(user)
        return "250 OK"


class BaseHTTPService(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Content-Type", "application/json")

    def is_valid_uuid(self, uuid):
        return bool(uuid)

    def write_error(self, *args, **kwargs):
        _, err, _ = kwargs["exc_info"]
        status = getattr(err, "status_code", 500)
        self.set_status(status)
        self.write({"code": status})
        self.finish()


class SmtpMailBoxDetailHandler(BaseHTTPService):
    def get(self, uuid, mail_id):
        user = User.get_or_none(uuid=uuid)
        if user is None:
            raise HTTPError(404)
        mail = Mail.get_or_none(user=user, id=mail_id)
        mail = mail.dict() if mail else {}
        self.finish(mail)


class SmtpMailBoxIframeLoadHandler(BaseHTTPService):
    def set_default_headers(self):
        self.set_header("Content-Type", "text/html; charset=UTF-8")

    def get(self, uuid, mail_id):
        user = User.get_or_none(uuid=uuid)
        if user is None:
            raise HTTPError(404)
        mail = Mail.get_or_none(user=user, id=mail_id)
        mail = mail.dict() if mail else {}
        html = mail.get("html_content", "") or mail.get("content")
        html = html.strip()
        self.write('<base target="_blank">')
        self.write('<meta name="referrer" content="none">')
        if not html.startswith("<"):
            html = '<pre>%s</pre>' % html
        self.finish(html)


class SmtpMailBoxIframeNewtabHandler(BaseHTTPService):
    def set_default_headers(self):
        self.set_header("Content-Type", "text/html; charset=UTF-8")

    def get(self, uuid, mail_id):
        src = "/mail/{}/{}/iframe".format(uuid, mail_id)
        self.render("iframe.html", src=src)


class SmtpMailBoxRssHandler(BaseHTTPService):
    def set_default_headers(self):
        self.set_header("Content-Type", "text/xml; charset=UTF-8")

    def initialize(self, domain):
        self.domain = domain

    def get(self, uuid):
        user = User.get_or_none(uuid=uuid)
        if user is None:
            raise HTTPError(404)
        user.last_active = time.time()
        user.save()  # prevent schd auto remove
        tz = time.strftime("%z")
        self.render("rss.xml", tz=tz, domain=self.domain, user=user, server=self.request.headers["Host"])


class SmtpUserHandler(BaseHTTPService):
    def post(self, uuid=None):
        if self.request.uri == "/user/random":
            # 生成新的随机UUID
            uuid = uuid4().hex[:8]
        elif self.request.uri == "/user/custom":
            try:
                data = json.loads(self.request.body.decode("utf-8"))
                uuid = data.get("uuid", "").strip()  # 从请求体获取自定义UUID，并去除前后空白
                domain = data.get("domain", "").strip()  # 从请求体获取自定义域名
                if domain not in email_domains:
                    raise HTTPError(400, log_message="Invalid Domain")  # 验证域名是否有效
            except json.JSONDecodeError:
                raise HTTPError(400, log_message="Invalid JSON")  # JSON解析失败返回400错误
        else:
            raise HTTPError(404)  # 未知路径返回404错误

        # 如果UUID为空，返回400错误
        if not uuid:
            raise HTTPError(400, log_message="UUID cannot be empty")

        # 创建用户或更新最后活动时间
        user, created = User.get_or_create(uuid=uuid)
        user.last_active = time.time()
        user.save()

        # 返回用户数据
        self.set_cookie("uuid", user.uuid, expires_days=2**16)
        self.finish(user.dict())


class SmtpMailBoxHandler(BaseHTTPService):
    def get(self, uuid):
        user = User.get_or_none(uuid=uuid)
        if user is None:
            raise HTTPError(404)
        mail = user.mail.select().order_by(Mail.send_time.desc()).limit(32)
        ret = [item.dict(exclude=[Mail.content, Mail.html_content]) for item in mail]
        self.finish(json.dumps(ret))


class SmtpIndexHandler(BaseHTTPService):
    def set_default_headers(self):
        self.set_header("Content-Type", "text/html")

    def initialize(self, domain):
        self.domain = domain

    def get(self):
        self.render("index.html", domain=self.domain)


class SmtpIntroHandler(BaseHTTPService):
    def set_default_headers(self):
        self.set_header("Content-Type", "text/html")

    def get(self):
        self.render("intro.html")


class DomainListHandler(BaseHTTPService):
    def get(self):
        self.finish(json.dumps(email_domains))


def schd_cleaner(seconds, interval):
    logger = logging.getLogger("cleaner")
    while True:
        time.sleep(interval)
        logger.info("user clean task is running")
        for user in User.select().where(User.last_active < (time.time() - seconds)):
            logger.warning("clean user data: %s" % user.uuid)
            user.delete_instance(True)


if __name__ == "__main__":
    define("domain", type=str)
    define("database", type=str, default="mail.db")
    define("listen", type=str, default="0.0.0.0")
    define("port", type=int, default=9999)
    options.parse_command_line()

    tornado.ioloop.IOLoop.configure("tornado.platform.asyncio.AsyncIOLoop")
    database.init(
        options.database,
        pragmas={"locking_mode": "NORMAL", "journal_mod": "wal", "synchronous": "OFF"},
    )
    templates = os.path.join(os.path.dirname(__file__), "templates")
    statics = os.path.join(os.path.dirname(__file__), "static")
    server = tornado.web.Application(
        [
            ("/intro", SmtpIntroHandler),
            (
                "/favicon.ico",
                tornado.web.StaticFileHandler,
                dict(url="/static/favicon.ico", permanent=False),
            ),
            ("/", SmtpIndexHandler, dict(domain=options.domain)),
            ("/mail/([^/]+)/(\d+)/iframe", SmtpMailBoxIframeLoadHandler),
            ("/mail/([^/]+)/(\d+)/show", SmtpMailBoxIframeNewtabHandler),
            ("/mail/([^/]+)/(\d+)", SmtpMailBoxDetailHandler),
            ("/mail/([^/]+)/rss", SmtpMailBoxRssHandler, dict(domain=options.domain)),
            ("/mail/([^/]+)", SmtpMailBoxHandler),
            ("/user/([^/]*)?", SmtpUserHandler),
            ("/user/random", SmtpUserHandler),  # 添加此行处理随机邮箱生成
            ("/user/custom", SmtpUserHandler),  # 添加此行处理自定义邮箱
            ("/domains", DomainListHandler),  # 新增API端点以获取邮箱后缀列表
        ],
        template_path=templates,
        static_path=statics,
    )

    server.listen(options.port, address=options.listen, xheaders=True)

    SmtpdHandler.domains = email_domains
    smtp = Controller(SmtpdHandler(), hostname="0.0.0.0", port=25)
    smtp.start()

    User.create_table()
    Mail.create_table()

    cleaner = threading.Thread(target=schd_cleaner, args=(7 * 86400, 600))
    cleaner.start()

    loop = asyncio.get_event_loop()
    loop.run_forever()
