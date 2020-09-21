import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import requests

import config
import imgkit
import seaborn as sns
import telegram
from requests_toolbelt import sessions

logging.basicConfig(
    filename=config.LOG_DIR,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    level=logging.DEBUG,
)


def convert_timezone(date_obj, ref_tz, target_tz):
    ref = pytz.timezone(ref_tz)
    target = pytz.timezone(target_tz)
    date_obj_aware = ref.localize(date_obj)

    return date_obj_aware.astimezone(target)


def get_endpoint(endpoint, params=None):
    with sessions.BaseUrlSession(base_url="https://api.covid19api.com/") as session:
        try:
            response = session.get(endpoint)
            response.raise_for_status()
            logging.info(f"Request successful for endpoint={endpoint}.")
        except requests.exceptions.HTTPError as e:
            logging.error(f"{e}. Retrying...")
            response = get_endpoint(endpoint)
    return response


def parse_countries(countries, sort_key, ascending=True):
    table = pd.DataFrame.from_dict(countries)
    table.drop(columns=["CountryCode", "Date", "Slug"], inplace=True)
    cols = config.TABLE_COLUMNS
    table = table[cols]
    return table.sort_values(sort_key, ascending=ascending)


def split_table(table, size=10):
    return [table[i : i + size] for i in np.arange(0, table.shape[0], size)]


def style_table(table, palette):
    cm = sns.light_palette(palette, as_cmap=True)
    formatter = {col: "{:,d}" for col in table.dtypes[table.dtypes == np.int64].index}
    table_styles = [
        {"selector": "", "props": [("width", "100%"), ("align", "center")]},
        {
            "selector": "th, td, .col0",
            "props": [
                ("background-color", "#ffffff"),
                ("color", "#000000"),
                ("text-align", "left"),
                ("border", "0px"),
                ("font-family", "Arial, Helvetica, sans-serif"),
                ("padding", "0.25em"),
            ],
        },
    ]
    style = (
        table.style.format(formatter)
        .background_gradient(cmap=cm)
        .set_table_styles(table_styles)
    )

    return style.hide_index().render()


class CovidBot(object):
    def __init__(self, chat_id, token):
        self.chat_id = chat_id
        self.bot = telegram.Bot(token)

    def send_message(self, message, parse_mode=None):
        self.bot.send_chat_action(
            chat_id=self.chat_id, action=telegram.ChatAction.TYPING
        )
        self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode=parse_mode)

    def send_photo(self, fname, timeout=60):
        self.bot.send_chat_action(
            chat_id=self.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO
        )
        self.bot.send_photo(
            chat_id=self.chat_id, photo=open(fname, "rb"), timeout=timeout
        )

    def send_photos(self, fnames, timeout=60):
        photos = [telegram.InputMediaPhoto(open(fname, "rb")) for fname in fnames]
        self.bot.send_chat_action(
            chat_id=self.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO
        )
        try:
            self.bot.send_media_group(
                chat_id=self.chat_id, media=photos, timeout=timeout
            )
        except telegram.error.BadRequest as e:
            logging.error(f"{e}. Retrying one more time...")
            self.send_photos(fnames, timeout=timeout)


def main():
    data = get_endpoint("/summary").json()

    world = data["Global"]
    world["Country"] = "Global"

    countries = data["Countries"]
    countries.append(world)

    ref_date = datetime.strptime(data["Date"], config.REF_FORMAT)
    target_date = convert_timezone(ref_date, config.REF_TZ, config.TARGET_TZ)
    table = parse_countries(data["Countries"], "TotalConfirmed", ascending=False)
    tables = split_table(table, size=config.TABLE_ROWS)

    fnames = []
    for idx, tab in enumerate(tables, 1):
        html = style_table(tab, "red")
        fname = f"{config.OUTPUT_DIR}/table_{idx}.png"
        imgkit.from_string(html, fname, options={"quiet": ""})
        fnames.append(fname)

    bot = CovidBot(chat_id=config.CHAT_ID, token=config.BOT_TOKEN)
    bot.send_message(
        f"COVID-19 summary statistics as of *{target_date.strftime(config.TARGET_FORMAT)}*",
        parse_mode="markdown",
    )

    batch_size = len(fnames) // 2
    first_batch, second_batch = fnames[:batch_size], fnames[batch_size:]
    bot.send_photos(first_batch, timeout=300)
    bot.send_photos(second_batch, timeout=300)


if __name__ == "__main__":
    main()
