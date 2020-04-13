import requests
import configparser
import mysql.connector
from datetime import datetime
from time import sleep, time

## For the time being
user_names = []
user_list = []
broadcast = False
check_leaderboard = False
matches = []
game_running = False
last_game_end_time = time()
announce_solo_games = False
check_leaderboard_times = 0
restarted = True

###########
# Configs #
###########

# Get database config
config = configparser.RawConfigParser()
config.read("./database.ini")
dbhost = config.get("Database", "dbhost")
dbport = config.get("Database", "dbport")
database = config.get("Database", "database")
dbuser = config.get("Database", "dbuser")
dbpass = config.get("Database", "dbpass")

# Get the Database running
db = mysql.connector.connect(host=dbhost,
                             port=dbport,
                             database=database,
                             user=dbuser,
                             password=dbpass)
cursor = db.cursor()
cursor.execute("SET NAMES utf8mb4;")
cursor.execute("SET CHARACTER SET utf8mb4;")
cursor.execute("SET character_set_connection=utf8mb4;")

# Telegram token
sqlquery = "SELECT config_value FROM configs WHERE config_name = 'telegram_token'"
cursor.execute(sqlquery)
records = cursor.fetchone()
tgbot_token = records[0]

# Broadcast channel
sqlquery = "SELECT config_value FROM configs WHERE config_name = 'broadcast_channel'"
cursor.execute(sqlquery)
records = cursor.fetchone()
broadcast_channel = records[0]

##############
# user class #
##############

class User:
    def __init__(self, name, rating_solo, rating_team, last_update, rank_solo, rank_team, profile_id, rating_solo_announced, rating_team_announced):
        self.name = name
        self.rating_solo = rating_solo
        self.rating_team = rating_team
        self.last_update = last_update
        self.rank_solo = rank_solo
        self.rank_team = rank_team
        self.profile_id = profile_id
        self.rating_solo_announced = rating_solo_announced
        self.rating_team_announced = rating_team_announced
        self.last_lobby = None

###################
# ao2.net methods #
###################

# API from https://aoe2.net/#api and https://aoe2.net/#nightbot

# Get leaderboard from bot
def get_leaderboard(leaderboard_id, start, count):
    try:
        api_url = "https://aoe2.net/api/leaderboard?game=aoe2de&leaderboard_id={}&start={}&count={}".format(leaderboard_id, start, count)
        print(api_url)
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_leaderboard(): {}".format(error))
        return False

# Get a the stats from a player
def get_player_stats(leaderboard_id, profile_id):
    try:
        api_url = "https://aoe2.net/api/leaderboard?game=aoe2de&leaderboard_id={}&profile_id={}".format(leaderboard_id, profile_id)
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_player_stats(): {}".format(error))
        return False


# Get the most recent full game info
def get_last_match(profile_id):
    try:
        api_url = "https://aoe2.net/api/player/lastmatch?game=aoe2de&profile_id={}".format(profile_id)
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_last_match(): {}".format(error))
        return False


# Get a simple matchup string i.e: " Player 1 as CIV VS Player 2 as CIV on MAP"
def get_match_simple(profile_id):
    try:
        api_url = "https://aoe2.net/api/nightbot/match?profile_id={}".format(profile_id)
        api_response = requests.get(api_url)
        return api_response.text
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_match_simple(): {}".format(error))
        return False

####################
# Telegram methods #
####################

# Get messages send to the telegram bot
def get_messages(offset_func):
    try:
        offset_url = "https://api.telegram.org/bot" + str(tgbot_token) + "/getUpdates?offset=" + offset_func
        bot_messages = requests.get(offset_url)
        return bot_messages.json()
    except Exception as error:
        print("Error in get_messages(): {}".format(error))
        return False

# Send message to a chat
def send_message(chat, message_func):
    try:
        api_response = requests.get("https://api.telegram.org/bot" + str(tgbot_token) + "/sendMessage?chat_id=" + str(chat) + "&text=" + str(message_func))
        api_response = api_response.json()

        # Log to database
        sqlquery = "INSERT INTO logs (type, message, telegram_message_id) VALUES (\"{}\", \"{}\", \"{}\")".format("message", api_response["result"]["text"], api_response["result"]["message_id"])
        cursor.execute(sqlquery)
        db.commit()

        return True
    except Exception as error:
        print("Error in send_message(): {}".format(error))
        return False

# Edit telegram message
def edit_message(chat, message_id, message_func):
    try:
        api_response = requests.get("https://api.telegram.org/bot{}/editMessageText?chat_id={}&message_id={}&text={}".format(tgbot_token, chat, message_id, message_func))
        print(api_response.text)
        return True
    except Exception as error:
        print("Error in edit_message(): {}".format(error))
        return False

#######
# Bot #
#######

# Check for team game
def check_teamgame(lobby_id):
    for user in user_list:
        if user.last_lobby == lobby_id:
            return True
    return False

# Get enabled users from database
sqlquery = "select * from users"
cursor.execute(sqlquery)
records = cursor.fetchall()

# Create list of active users
for player in records:
    user_object = User(player[1], player[2], player[3], player[4], player[6], player[7], player[8], player[9], player[10])
    user_list.append(user_object)

# Set the user.name attribute for every user in the user_list
for user in user_list:
    user_names.append(user.name)

while True:
    # Check if we have a connection to the database or try to reconnect
    if not db.is_connected():
        cursor = db.cursor()
        print("Reconnected to Database")

    # ClI output to see some action
    print("Checking Games -", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Check if user has an unfinished game
    for user in user_list:
        # Get all info into the variable game to have access without triggering the api
        game = get_last_match(user.profile_id)
        # Check if the game is still running
        # Also check if this lobby is know so we do not post games multiple times to the chat
        if game and not game["last_match"]["finished"] and user.last_lobby != game["last_match"]["lobby_id"]:
            # CLI output
            print("Unfinished game found for", user.name)
            # Get the match string vom aoe2.net api
            simple_match = get_match_simple(user.profile_id)
            # Ignore if game vs AI
            if not simple_match == "Game type not supported (AI)":
                # Make sure its not a team game to avoid double posts
                if check_teamgame(game["last_match"]["lobby_id"]):
                    # Set lobby id to track it
                    user.last_lobby = game["last_match"]["lobby_id"]
                else:
                    message = "New Match: " + str(simple_match)
                    # CLI output
                    print(message)
                    # Log to database
                    try:
                        sqlquery = "INSERT INTO logs (type, message) VALUES (\"{}\", \"{}\")".format("match", message)
                        cursor.execute(sqlquery)
                        db.commit()
                    except Exception as error:
                        print("Problem inserting last match to database! ")
                        print("Error: {}".format(error))
                    # Check if its a 1v1
                    if game["last_match"]["num_players"] == 2:
                        # If announce_solo_games is true we send out a message
                        if announce_solo_games:
                            send_message(broadcast_channel, message)
                    # If it is not a 1v1 send message to channel
                    else:
                        send_message(broadcast_channel, message)
                    # Set lobby id to track it
                    user.last_lobby = game["last_match"]["lobby_id"]
            # If it is an AI game we just print it to the CLI
            else:
                print("Game VS AI")

        # If game is done, check the leaderboard
        # "finished" is NULL as long as the game is going on
        elif game and game["last_match"]["finished"]:
            # Check if we already saw this game
            # Note: The time updates multiple times on the api
            if last_game_end_time < game["last_match"]["finished"]:
                print("Last game is done for", user.name)
                # We need to remember the finish time from last game
                # so we do not post its finish multiple times
                last_game_end_time = game["last_match"]["finished"]
                # Setup the leaderboard check
                # We want to check the leaderboard more times since we do not know when it updates
                if check_leaderboard_times == 0:
                    check_leaderboard_times = 5

    # Check leaderboard if there was a game
    # or after a restart
    if check_leaderboard_times > 0 or restarted:
        print("Checking leaderboard!")
        broadcast = False
        check_leaderboard_times = check_leaderboard_times - 1

        # Check stats for every user
        for user in user_list:
            # Leaderboard 3 = 1v1 ladder
            player = get_player_stats(3, user.profile_id)

            # Player True = Got API response
            # Player False = no API response
            if player:
                for entry in player["leaderboard"]:
                    if user.rating_solo != entry["rating"]:

                        # Calc the rating diff
                        user_rating_diff = entry["rating"] - user.rating_solo

                        # Set the new user rating
                        user.rating_solo = entry["rating"]
                        sqlquery = "UPDATE users SET rating_solo = '{}' WHERE name = '{}'".format(user.rating_solo, user.name)
                        cursor.execute(sqlquery)
                        print("Set {} solo rating to {} - Update time: {}".format(user.name, user.rating_solo, user.last_update))

                        if announce_solo_games:
                            # Edit last posted game to show win or lose
                            # Select telegram_message_id from last game this player participated in
                            sqlquery = "SELECT telegram_message_id FROM logs WHERE type = 'message' AND message LIKE '%{}%' ORDER BY `id` DESC LIMIT 1;".format(user.name)
                            cursor.execute(sqlquery)
                            records = cursor.fetchone()
                            telegram_message_id = records[0]

                            # Get last match so we can construct the new message
                            sqlquery = "SELECT message FROM logs WHERE type = 'match' AND message LIKE '%{}%' ORDER BY `id` DESC LIMIT 1;".format(user.name)
                            cursor.execute(sqlquery)
                            records = cursor.fetchone()
                            last_match_message = records[0]

                            # Construct new message
                            if user_rating_diff > 0:
                                game_result = "\n==> Gewonnen!! \U0001F3C6 \U0001F4AA"
                            else:
                                game_result = "\n==> Verloren! \U0001F44E \U0001F44E"
                            message_edited = last_match_message + game_result

                            # Use edit function to post new message
                            edit_message(broadcast_channel, telegram_message_id, message_edited)

                    if abs(user.rating_solo-user.rating_solo_announced) > 50:
                        broadcast = True

                    user.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    sqlquery = "UPDATE users SET last_update = '{}' WHERE name = '{}'".format(user.last_update, user.name)
                    cursor.execute(sqlquery)

                    user.steam_id = entry["steam_id"]
                    sqlquery = "UPDATE users SET steam_id = '{}' WHERE name = '{}'".format(user.steam_id, user.name)
                    cursor.execute(sqlquery)

                    user.rank_solo = entry["rank"]
                    sqlquery = "UPDATE users SET rank_solo = '{}' WHERE name = '{}'".format(user.rank_solo, user.name)
                    cursor.execute(sqlquery)

                    db.commit()

        # Check stats for every user
        for user in user_list:
            # Leaderboard 4 = Team ladder
            player = get_player_stats(4, user.profile_id)

            # Player True = Got API response
            # Player False = no API response
            if player:
                for entry in player["leaderboard"]:
                    if user.rating_team != entry["rating"]:

                        # Calc the rating diff
                        user_rating_diff = entry["rating"] - user.rating_team

                        # Set the new user rating
                        user.rating_team = entry["rating"]
                        sqlquery = "UPDATE users SET rating_team = '{}' WHERE name = '{}'".format(user.rating_team, user.name)
                        cursor.execute(sqlquery)
                        print("Set {} team rating to {} - Update time: {}".format(user.name, user.rating_team, user.last_update))

                        # Edit last posted game to show win or lose
                        # Select telegram_message_id from last game this player participated in
                        sqlquery = "SELECT telegram_message_id FROM logs WHERE type = 'message' AND message LIKE '%{}%' ORDER BY `id` DESC LIMIT 1;".format(user.name)
                        cursor.execute(sqlquery)
                        records = cursor.fetchone()
                        telegram_message_id = records[0]
                        print("The message ID to EDIT = {}".format(telegram_message_id))

                        # Get last match so we can construct the new message
                        sqlquery = "SELECT message FROM logs WHERE type = 'match' AND message LIKE '%{}%' ORDER BY `id` DESC LIMIT 1;".format(user.name)
                        cursor.execute(sqlquery)
                        records = cursor.fetchone()
                        last_match_message = records[0]
                        print("Last match was {}".format(last_match_message))

                        # Construct new message
                        if user_rating_diff > 0:
                            game_result = "\n==> Gewonnen!! \U0001F3C6 \U0001F4AA"
                        else:
                            game_result = "\n==> Verloren! \U0001F44E \U0001F44E"
                        message_edited = last_match_message + game_result

                        # Use edit function to post new message
                        edit_message(broadcast_channel, telegram_message_id, message_edited)

                    if abs(user.rating_team-user.rating_team_announced) > 50:
                        broadcast = True

                    user.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    sqlquery = "UPDATE users SET last_update = '{}' WHERE name = '{}'".format(user.last_update, user.name)
                    cursor.execute(sqlquery)

                    user.steam_id = entry["steam_id"]
                    sqlquery = "UPDATE users SET steam_id = '{}' WHERE name = '{}'".format(user.steam_id, user.name)
                    cursor.execute(sqlquery)

                    user.rank_team = entry["rank"]
                    sqlquery = "UPDATE users SET rank_team = '{}' WHERE name = '{}'".format(user.rank_team, user.name)
                    cursor.execute(sqlquery)

                    db.commit()

        if broadcast:
            # Solo 1v1
            user_list_with_rating = []
            for user in user_list:
                if user.rating_solo:
                    user_list_with_rating.append(user)

            # Sort the user-list on rating
            user_list_sorted = sorted(user_list_with_rating, key=lambda x: x.rating_solo, reverse=True)

            # Construct the leaderboard post
            leaderboard_solo = "1v1 Leaderboard:\n----------------------\n"
            for user in user_list_sorted:
                if user.rating_solo:
                    if user.rating_solo > user.rating_solo_announced:
                        rating_diff = str(user.rating_solo - user.rating_solo_announced)
                        leaderboard_solo = leaderboard_solo + "Rank: {} Rating: {} \U00002b06 {}  {}\n".format(user.rank_solo, user.rating_solo, rating_diff, user.name)
                    elif user.rating_solo < user.rating_solo_announced:
                        rating_diff = str(user.rating_solo_announced - user.rating_solo)
                        leaderboard_solo = leaderboard_solo + "Rank: {} Rating: {} \U00002b07 {} {}\n".format(user.rank_solo, user.rating_solo, rating_diff, user.name)
                    else:
                        leaderboard_solo = leaderboard_solo + "Rank: {} Rating: {} {}\n".format(user.rank_solo, user.rating_solo, user.name)

            # Team
            user_list_with_rating = []
            for user in user_list:
                if user.rating_team:
                    user_list_with_rating.append(user)

            # Sort the user-list on rating
            user_list_sorted = sorted(user_list_with_rating, key=lambda x: x.rating_team, reverse=True)

            # Construct the leaderboard post
            leaderboard_team = "Team Leaderboard:\n------------------------\n"
            for user in user_list_sorted:
                if user.rating_team:
                    if user.rating_team > user.rating_team_announced:
                        rating_diff = str(user.rating_team - user.rating_team_announced)
                        leaderboard_team = leaderboard_team + "Rank: {} Rating: {} \U00002b06 {} {}\n".format(user.rank_team, user.rating_team, rating_diff, user.name)
                    elif user.rating_team < user.rating_team_announced:
                        rating_diff = str(user.rating_team_announced - user.rating_team)
                        leaderboard_team = leaderboard_team + "Rank: {} Rating: {} \U00002b07 {} {}\n".format(user.rank_team, user.rating_team, rating_diff, user.name)
                    else:
                        leaderboard_team = leaderboard_team + "Rank: {} Rating: {} {}\n".format(user.rank_team, user.rating_team, user.name)

            # Send out the leaderboard
            one_msg = leaderboard_solo + "\n" + leaderboard_team
            send_message(broadcast_channel, one_msg)
            print("Broadcasted the leaderboard!")

            # Update the user ratings in the database
            for user in user_list:
                if user.rating_solo:
                    user.rating_solo_announced = user.rating_solo
                    sqlquery = "UPDATE users SET rating_solo_announced = '{}' WHERE name = '{}'".format(user.rating_solo_announced, user.name)
                    cursor.execute(sqlquery)
                if user.rating_team:
                    user.rating_team_announced = user.rating_team
                    sqlquery = "UPDATE users SET rating_team_announced = '{}' WHERE name = '{}'".format(user.rating_team_announced, user.name)
                    cursor.execute(sqlquery)

                db.commit()
        restarted = False
    # Wait 60 Seconds between checks
    sleep(60)
