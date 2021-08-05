#!/usr/bin/env python3

import sys
import boto3
import configparser
from datetime import date, timedelta
import logging
import json
import urllib.parse
from botocore.exceptions import BotoCoreError


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

    print(chart_url)


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


def main():
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

    start, end = getDays()
    cost = getCost(client, start, end)
    getChart(url, cost)


if __name__ == "__main__":
    main()
