#!/usr/bin/env python3

import os
import boto3
import configparser
from datetime import date, timedelta
import logging
from botocore.exceptions import BotoCoreError
from slack_bolt import App  # type: ignore
from quickchart import QuickChart, QuickChartFunction

account_count = 1
accounts = []


def get_days():
    today = date.today()
    start = today - timedelta(days=8)
    end = today - timedelta(days=1)

    start = str(start)
    end = str(end)

    return start, end


def get_cost(aws_client: boto3.client, start: str, end: str):
    response = aws_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        # Filter={
        #     'Dimensions': {
        #         'Key': 'LINKED_ACCOUNT',
        #         'Values': accounts,
        #         'MatchOptions': ['EQUALS']
        #     }
        # },
        Metrics=[
            "AmortizedCost",
        ],
    )
    return response


def get_chart(cost_response: dict):
    qc = QuickChart()
    qc.width = 500
    qc.height = 300
    qc.background_color = "transparent"
    labels = []
    data = []
    results = cost_response["ResultsByTime"]

    for result in results:
        labels.append(result["TimePeriod"]["Start"])
        formatted_amount = round(
            float(
                result["Total"]["AmortizedCost"]["Amount"]), 2)
        data.append(formatted_amount)

    qc.config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Cost in $",
                "data": data,
                "backgroundColor": QuickChartFunction(
                    "getGradientFillHelper('vertical', \
                    ['rgba(63, 100, 249, 0.2)', \
                    'rgba(255, 255, 255, 0.2)'])"
                ),
            }]
        },
        "options": {
            "plugins": {
                "tickFormat": {
                    "style": "currency",
                    "currency": "USD"
                },
                "datalabels": {
                    "anchor": "end",
                    "align": "top",
                    "color": "#fff",
                    "backgroundColor": "rgba(34, 139, 34, 0.6)",
                    "borderColor": "rgba(34, 139, 34, 1.0)",
                    "borderWidth": 1,
                    "borderRadius": 5,
                    "formatter": QuickChartFunction(
                        '''(value) => { return '$' + value; }'''
                    ),
                }
            }
        },
    }

    return qc.get_url()


def generate_config(config_file: str):
    parsed_config = configparser.ConfigParser()
    parsed_config.read(config_file)

    if not parsed_config.has_section("AWS"):
        logging.warning(
            "AWS section not defined in config.ini. \
            Assuming AWS keys are provided by ENV VAR"
        )

    return parsed_config


config = generate_config("config.ini")
url = config["quickchart"]["url"]

# I hate how this boto checking is implemented...
# but I don't know how to do this better.
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
        logging.warning(
            "no AWS credentials found, assuming credentials will be provided later \
            or your forgot to provide via ENV VAR or config.ini \n \
                actual BotoCore error: " + format(str(e))
        )

try:
    slack_token = config["slack"]["slack_bot_token"]
    slack_signing_secret = config["slack"]["slack_signing_secret"]
except KeyError:
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_SIGNING_SECRET"):
        slack_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_signing_secret = os.environ.get("SLACK_SIGNING_SECRET")
    else:
        logging.critical("no slack app credentials found")
        os._exit(2)

app = App(token=slack_token, signing_secret=slack_signing_secret)


def account_modal_view(number_of_accounts: int):
    view = {
        "title": {
            "type": "plain_text",
            "text": "Configure Parsimony"
        },
        "submit": {
            "type": "plain_text",
            "text": "Submit"
        },
        "blocks": [
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "add_account",
                        "text": {
                            "type": "plain_text",
                            "text": "Add another account  "
                        }
                    }
                ]
            }
        ],
        "type": "modal",
        "callback_id": "config_view"
    }
    for i in range(number_of_accounts):
        account_input = {
            "type": "input",
            "block_id": f"account_{i}",
            "element": {
                "type": "plain_text_input",
                "action_id": f"account_input_{i}",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Account Number"
                }
            },
            "label": {
                "type": "plain_text",
                "text": "AWS Account"
            }
        }
        view["blocks"].append(account_input)
    return view


@app.event("app_home_opened")  # type: ignore
def update_home_tab(client, event, logger):
    try:
        # views.publish is the method that your
        # app uses to push a view to the Home tab
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
                            "text": "Available Commands Are: \n `/parsimony` \
                            - run parsimony with defaults",
                        },
                    },
                ],
            },
        )

    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


@app.command("/parsimony")  # type: ignore
def slash_parsimony(ack, respond, logger):
    ack()
    try:
        start, end = get_days()
        cost = get_cost(client, start, end)
        chart_url = get_chart(cost)
        ack()
        respond(
            {
                "response_type": "in_channel",
                "blocks": [
                    {
                        "type": "image",
                        "title": {"type": "plain_text",
                                  "text": "Latest data"},
                        "block_id": "quickchart-image",
                        "image_url": chart_url,
                        "alt_text": "Chart showing latest data",
                    }
                ],
            }
        )

    except Exception as e:
        logger.error(f"Error publishing slash parsimony: {e}")


@app.command("/parsimony-config")  # type: ignore
def open_modal(ack, body, client):
    # Acknowledge the command request
    ack()
    # Call views_open with the built-in client
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
        # if you are seeing invalid trigger id, token might be wrong
        trigger_id=body["trigger_id"],
        # View payload
        view=account_modal_view(account_count)
    )


@app.action("add_account")  # type: ignore
def update_modal(ack, body, client):
    global account_count
    account_count += 1
    # Acknowledge the button request
    ack()
    # Call views_update with the built-in client
    client.views_update(
        # Pass the view_id
        view_id=body["view"]["id"],
        # String that represents view state
        # to protect against race conditions
        hash=body["view"]["hash"],
        # View payload with updated blocks
        view=account_modal_view(account_count)
    )


@app.view("config_view")  # type: ignore
def handle_submission(ack, body, client, view, logger):
    ack()
    global accounts
    for account_input in view["state"]["values"]:
        for account in view["state"]["values"][f"{account_input}"]:
            accounts.append(str((view["state"]
                                ["values"]
                                [f"{account_input}"]
                                [f"{account}"]
                                ["value"])))


if __name__ == "__main__":
    app.start(port=int(os.environ.get("PORT", 3000)))
