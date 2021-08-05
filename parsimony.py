#!/usr/bin/env python3

import os
import sys
import boto3
import configparser
from datetime import date, timedelta
import logging
import json
import urllib.parse
from botocore.exceptions import BotoCoreError
from botocore.signers import add_generate_presigned_post
from slack_bolt import App


def getDays():
    today = date.today()
    start = today - timedelta(days=today.weekday() + 1 % 7)
    end = start + timedelta(days=6)

    start = str(start)
    end = str(end)

    return start, end


def getCost(client: boto3.client, start: str, end: str):
    response = client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=[
            "AmortizedCost",
        ],
    )
    return response


def getChart(url, costResponse: dict):
    lables = []
    data = []
    results = costResponse["ResultsByTime"]

    for result in results:
        lables.append(result["TimePeriod"]["Start"])
        data.append(result["Total"]["AmortizedCost"]["Amount"])

    chart = {
        "type": "line",
        "data": {"labels": lables, "datasets": [{"label": "Cost in $", "data": data}]},
        "options": {
            "plugins": {
                "tickFormat": {
                    "style": "currency",
                    "currency": "USD",
                    "minimumFractionDigits": 10,
                },
                "datalabels": {
                    "anchor": "end",
                    "align": "top",
                    "color": "#fff",
                    "backgroundColor": "rgba(34, 139, 34, 0.6)",
                    "borderColor": "rgba(34, 139, 34, 1.0)",
                    "borderWidth": 1,
                    "borderRadius": 5,
                },
            }
        },
    }

    chart_json = urllib.parse.quote(json.dumps(chart))

    chart_url = url + "chart?c=" + chart_json

    return chart_url


def generateConfig(configFile: str):
    config = configparser.ConfigParser()
    config.read(configFile)

    if not config.has_section("AWS"):
        logging.warning(
            "AWS section not defined in config.ini. Assuming AWS keys are provided by ENV VAR"
        )
    else:
        if not config.has_option("AWS", "access_key"):
            logging.critical(
                "AWS section defined in config, but access_key not defined in AWS section"
            )
            sys.exit("fatal error")
        elif not config.has_option("AWS", "secret_key"):
            logging.critical(
                "AWS section defined in config, but secret_key not defined in AWS section"
            )
            sys.exit("fatal error")

    return config


config = generateConfig("config.ini")
url = config["quickchart"]["url"]

# I hate how this boto checking is implemented... but I dont know how to do this better.
try:
    client = boto3.client(
        "ce",
        aws_access_key_id=config["AWS"]["access_key"],
        aws_secret_access_key=config["AWS"]["aws_secret_key"],
    )
except KeyError:
    try:
        client = boto3.client("ce")
        sts = boto3.client("sts")
        sts.get_caller_identity()
    except BotoCoreError as e:
        logging.critical(
            "no AWS credentials found, please set credentials via ENV VAR or config.ini \n    actual BotoCore error: "
            + format(str(e))
        )
        sys.exit("fatal error")

try:
    slack_token = config["slack"]["slack_bot_token"]
    slack_signing_secret = config["slack"]["slack_signing_secret"]
except KeyError:
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_SIGNING_SECRET"):
        slack_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_signing_secret = os.environ.get("SLACK_SIGNING_SECRET")
    else:
        logging.critical("no slack app credentials found")
        sys.exit("fatal error")

app = App(token=slack_token, signing_secret=slack_signing_secret)

# start, end = getDays()
# cost = getCost(client, start, end)
# getChart(url, cost)


@app.event("app_home_opened")
def update_home_tab(client, event, logger):
    try:
        # views.publish is the method that your app uses to push a view to the Home tab
        client.views_publish(
            # the user that opened your app's app home
            user_id=event["user"],
            # the view object that appears in the app home
            view={
                "type": "home",
                "callback_id": "home_view",
                # body of the view
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Thanks for using Parsimony* :tada:",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Available Commands Are: \n `/parsimony` - run parsimony with defaults",
                        },
                    },
                ],
            },
        )

    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


@app.command("/parsimony")
def slash_parsimony(ack, respond, logger):
    try:
        start, end = getDays()
        cost = getCost(client, start, end)
        chart_url = getChart(url, cost)
        ack()
        respond(
            {
                "blocks": [
                    {
                        "type": "image",
                        "title": {"type": "plain_text", "text": "Latest data"},
                        "block_id": "quickchart-image",
                        "image_url": chart_url,
                        "alt_text": "Chart showing latest data",
                    }
                ]
            }
        )

    except Exception as e:
        logger.error(f"Error publishing slash parsimony: {e}")


if __name__ == "__main__":
    app.start(port=int(os.environ.get("PORT", 3000)))
