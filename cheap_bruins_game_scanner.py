import smtplib
import ssl
from datetime import datetime
from typing import List
import pytz
import requests as requests
import time
from requests.auth import HTTPBasicAuth

with open("secrets.txt", "r") as secret_key_file:
    SECRET_SEATGEEK_KEY, SECRET_STUBHUB_ID, SECRET_STUBHUB_SECRET, \
        SENDER_EMAIL, SENDER_SMTP_PASSWORD, PHONE_NUMBER = secret_key_file.readlines()

    SECRET_SEATGEEK_KEY = SECRET_SEATGEEK_KEY.strip("\n")
    SECRET_STUBHUB_ID = SECRET_STUBHUB_ID.strip("\n")
    SECRET_STUBHUB_SECRET = SECRET_STUBHUB_SECRET.strip("\n")
    SENDER_EMAIL = SENDER_EMAIL.strip("\n")
    SENDER_SMTP_PASSWORD = SENDER_SMTP_PASSWORD.strip("\n")
    PHONE_NUMBER = PHONE_NUMBER.strip("\n")

# Next three constants are
# Your email to sms domain. Reference: https://avtech.com/articles/138/list-of-email-to-sms-addresses/
EMAIL_DOMAIN = 'tmomail.net'
# SMTP server for your email address. Reference: https://domar.com/pages/smtp_pop3_server
SMTP_SERVER = 'smtp.gmail.com'
# SMTP port for your email address: Reference: https://domar.com/pages/smtp_pop3_server
SMTP_PORT = 465


class CheapBruinsGameScanner:
    class BruinsGame:
        def __init__(self, datetime_of_game, minimum_ticket_price, opponent, ticket_seller):

            self.ticket_seller = ticket_seller
            self.local_time = self.convert_utc_to_est(datetime_of_game)
            self.local_time_formatted = self.format_datetime_to_string(self.local_time)

            self.opponent = opponent
            self.minimum_ticket_price = minimum_ticket_price

            self.has_sms_already_been_sent = False

        def __str__(self):
            string = ''
            string += f'{self.local_time_formatted}\n'
            string += f'Boston Bruins vs {self.opponent}\n'
            string += f'${self.minimum_ticket_price} on {self.ticket_seller}'
            string += " (after fees)"

            return string

        @staticmethod
        def format_datetime_to_string(datetime_to_format):
            return datetime_to_format.strftime(f'%A, %B %d, %Y %H:%M EST')

        def convert_utc_to_est(self, datetime_utc):
            year = datetime_utc[:4]
            datetime_utc = datetime_utc[5:]

            month = ""
            for char in datetime_utc:
                if char == '-':
                    datetime_utc = datetime_utc[1:]
                    break
                month += char
                datetime_utc = datetime_utc[1:]

            day = ""
            for char in datetime_utc:
                if char == 'T':
                    datetime_utc = datetime_utc[1:]
                    break
                day += char
                datetime_utc = datetime_utc[1:]

            hour = ""
            for char in datetime_utc:
                if char == ':':
                    datetime_utc = datetime_utc[1:]
                    break
                hour += char
                datetime_utc = datetime_utc[1:]

            minute = ""
            for char in datetime_utc:
                if char == ':':
                    datetime_utc = datetime_utc[1:]
                    break
                minute += char
                datetime_utc = datetime_utc[1:]

            second = ""
            for char in datetime_utc:
                second += char
                datetime_utc = datetime_utc[1:]

            year = int(year)
            month = int(month)
            day = int(day)
            hour = int(hour)
            minute = int(minute)
            second = int(second)

            if self.ticket_seller == "Seatgeek":
                datetime_est: datetime = datetime(year, month, day, hour, minute, second, tzinfo=pytz.utc).astimezone(
                    pytz.timezone('US/Eastern'))

            else:
                datetime_est = datetime(year, month, day, hour, minute, second,
                                        tzinfo=pytz.timezone('US/Eastern'))

            return datetime_est

    def __init__(self, output_price_threshold, sms_price_threshold):
        self.OUTPUT_PRICE_THRESHOLD = output_price_threshold
        self.SMS_PRICE_THRESHOLD = sms_price_threshold
        self.list_of_cheap_games: List[CheapBruinsGameScanner.BruinsGame] = []

        self.STUBHUB_API_TOKEN = ""

        self.time_between_price_checks_seconds = 300

        while True:
            self.list_of_cheap_games.clear()
            try:
                self.scan_seatgeek_games()
            except Exception as e:
                print(e)
            # self.scan_ticketmaster_games
            try:
                self.scan_stubhub_games()
            except Exception as e:
                print(e)

            for game in self.list_of_cheap_games:
                if not game.has_sms_already_been_sent and game.minimum_ticket_price < self.SMS_PRICE_THRESHOLD:
                    self.send_game_alert(game)

            self.sort_list_of_cheap_games_by_date()

            self.write_to_output(self.list_of_cheap_games)
            time.sleep(self.time_between_price_checks_seconds)

    def sort_list_of_cheap_games_by_date(self):
        self.list_of_cheap_games = sorted(self.list_of_cheap_games, key=lambda game: game.local_time)

    def scan_seatgeek_games(self):
        seatgeek_response = requests.get(
            url=f'https://api.seatgeek.com/2/events?performers.id=2123&lowest_price.lte={self.OUTPUT_PRICE_THRESHOLD}'
                f'&venue.state=MA&per_page=60&client_id={SECRET_SEATGEEK_KEY}')
        seatgeek_response_json = seatgeek_response.json()

        for event in seatgeek_response_json['events']:
            lowest_price = event['stats']['lowest_price']
            date = event['datetime_utc']
            away_team = None

            for performer in event['performers']:
                if performer['name'] != "Boston Bruins":
                    away_team = performer['name']

            cheap_game = CheapBruinsGameScanner.BruinsGame(datetime_of_game=date, minimum_ticket_price=lowest_price,
                                                           opponent=away_team,
                                                           ticket_seller="Seatgeek")

            self.add_game_to_list_of_cheap_games(cheap_game)

    def scan_stubhub_games(self):

        stubhub_response = self.make_stubhub_api_request(self.STUBHUB_API_TOKEN)
        if stubhub_response.status_code == 401:
            self.STUBHUB_API_TOKEN = self.get_new_stubhub_token()
            stubhub_response = self.make_stubhub_api_request(self.STUBHUB_API_TOKEN)

        for game in stubhub_response.json().get('_embedded').get('items'):
            if (game.get('type') != 'Parking') and \
                    (game.get('_embedded').get('venue').get('name') == 'TD Garden') and \
                    (self.apply_stubhub_fee(game.get('min_ticket_price').get('amount')) < self.OUTPUT_PRICE_THRESHOLD):

                date = game.get('start_date')
                date = date[0:len(date) - 6]
                lowest_price = self.apply_stubhub_fee(game.get('min_ticket_price').get('amount'))
                away_team = None
                for category in game.get('_embedded').get('categories'):
                    if category.get('role') == 'AwayTeam':
                        away_team = category.get('name')

                cheap_game = CheapBruinsGameScanner.BruinsGame(datetime_of_game=date, minimum_ticket_price=lowest_price,
                                                               opponent=away_team, ticket_seller="Stubhub")

                self.add_game_to_list_of_cheap_games(cheap_game)

    @staticmethod
    def apply_stubhub_fee(ticket_price):
        return round(1.59 * ticket_price - 4.51, 2)

    @staticmethod
    def get_new_stubhub_token():
        basic = HTTPBasicAuth(SECRET_STUBHUB_ID, SECRET_STUBHUB_SECRET)
        response = requests.post(url="https://account.stubhub.com/oauth2/token",
                                 auth=basic,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                 data={'grant_type': 'client_credentials',
                                       'scope': 'read:events'})

        new_access_token = response.json().get('access_token')
        return new_access_token

    @staticmethod
    def make_stubhub_api_request(token):
        return requests.get(url="https://api.stubhub.net/catalog/events/search",
                            headers={"Authorization": f"Bearer {token}",
                                     'Content-Type': 'application/hal+json'},
                            params={'q': 'Boston Bruins',
                                    'page_size': 2000})

    def add_game_to_list_of_cheap_games(self, game_to_add: BruinsGame):

        if game_to_add.minimum_ticket_price is None:
            return

        duplicate_game = self.check_if_game_already_in_list(game_to_add)

        if duplicate_game is not None:
            if game_to_add.minimum_ticket_price < duplicate_game.minimum_ticket_price:
                self.list_of_cheap_games.remove(duplicate_game)
                self.list_of_cheap_games.append(game_to_add)

        else:
            self.list_of_cheap_games.append(game_to_add)

    def check_if_game_already_in_list(self, game_to_check: BruinsGame):
        for game_in_list in self.list_of_cheap_games:
            if game_to_check.local_time_formatted == game_in_list.local_time_formatted:
                return game_in_list
        return None

    def send_game_alert(self, game: BruinsGame):
        subject = "Cheap Bruins game alert!"
        message = f"\n${game.minimum_ticket_price} Bruins vs {game.opponent} on {game.local_time_formatted} on" \
                  f" {game.ticket_seller} "
        self.send_sms_via_email(number=PHONE_NUMBER, message=message, subject=subject)
        game.has_sms_already_been_sent = True
        time.sleep(3)

    @staticmethod
    def send_sms_via_email(number: str, message: str, subject: str, smtp_server: str = SMTP_SERVER,
                           smtp_port: int = SMTP_PORT,
                           sender_credentials: tuple = (SENDER_EMAIL, SENDER_SMTP_PASSWORD)):
        sender_email, email_password = sender_credentials
        receiver_email = f"{number}@{EMAIL_DOMAIN}"

        email_message = f"Subject:{subject}\nTo:{receiver_email}\n{message}"

        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=ssl.create_default_context()) as email:
            email.login(sender_email, email_password)
            email.sendmail(sender_email, receiver_email, email_message)

    def write_to_output(self, games: [BruinsGame]):

        string = ""

        last_updated_time = self.get_local_time()
        last_updated_time_formatted = self.BruinsGame.format_datetime_to_string(last_updated_time)
        string += f"Last updated on {last_updated_time_formatted}\n"

        string += f"------------------------------------------------------------------------\n\n" \
                  f"\t\t\t\tBruins games under price threshold (${self.OUTPUT_PRICE_THRESHOLD})\n\n" \
                  f"------------------------------------------------------------------------\n\n"
        for game in games:
            print(game)
            string += f"{game}\n\n"
        if len(games) == 0:
            string += f"No games under price threshold\n\n"

        with open("output.txt", "w+") as output:
            output.write(string)

    @staticmethod
    def get_local_time():
        return datetime.now(pytz.timezone('US/Eastern'))


if __name__ == '__main__':
    CheapBruinsGameScanner(output_price_threshold=70, sms_price_threshold=40)
