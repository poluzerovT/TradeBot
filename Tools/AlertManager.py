import json

# from telebot import
import telebot

class AlertManager:
    def __init__(self, config):

        self.token = config['telegram']['token']
        self.chat_id = config['telegram']['chat_id']
        self.bot = telebot.TeleBot(self.token)

    def send_message(self, msg, title=None):
        if isinstance(msg, dict):
            msg = json.dumps(msg, indent=4)
        if title:
            msg = f'{title.upper()}\n{msg}'
        self.bot.send_message(self.chat_id, msg)

