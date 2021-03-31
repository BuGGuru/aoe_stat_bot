import requests
import configparser
import mysql.connector
from datetime import datetime
from time import sleep, time
import json
from types import SimpleNamespace

# Globals needed
user_names = []
user_list = []
broadcast = False
check_leaderboard = False
matches_to_check = []
matches_processed = []
check_leaderboard_times = 0

# Configure these
amount_matches_to_check = 2
announce_solo_games = False
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
# leaderboard_id 3 = solo
# leaderboard_id 4 = group
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

# Get the last x game info
def get_last_matches(profile_id, amount):
    try:
        api_url = "https://aoe2.net/api/player/matches?game=aoe2de&profile_id={}&count={}".format(profile_id, amount)
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_last_matches(): {}".format(error))
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

# Get details about a specific match_id
def get_match_info(match_id):
    try:
        api_url = "https://aoe2.net/api/match?id={}".format(match_id)
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_match_info(): {}".format(error))
        return False

# Get API specific strings
def get_string_info():
    try:
        api_url = "https://aoe2.net/api/strings?game=aoe2de&language=en"
        api_response = requests.get(api_url)
        return api_response.json()
    except Exception as error:
        print("Got no data from the API!")
        print("Error in get_match_info(): {}".format(error))
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

        return api_response["result"]["message_id"]
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
    print("----------------- Search for games -----------------")
    print("Checking Games -", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("Games to Check from previous iteration:", matches_to_check)
    print("Games processed:", matches_processed)

    # Check if new games were played
    for user in user_list:
        games = get_last_matches(user.profile_id, amount_matches_to_check)
        if games:
            for game in games:
                if not game["match_id"] in matches_to_check and not game["match_id"] in matches_processed:
                    print("New game found for", user.name)
                    matches_to_check.append(game["match_id"])
                    # Post the new found game
                    if not restarted:
                        game_object = json.dumps(game)
                        game_object = json.loads(game_object, object_hook=lambda d: SimpleNamespace(**d))

                        team1 = ""
                        team2 = ""
                        translation = get_string_info()

                        for player in game_object.players:

                            # Get player rankings
                            if game_object.num_players == 2:
                                player_ranking_highest = str(get_player_stats(3, player.profile_id)["leaderboard"][0]["highest_rating"])
                            else:
                                player_ranking_highest = str(get_player_stats(4, player.profile_id)["leaderboard"][0]["highest_rating"])

                            # Sort teams
                            if player.team == 1:
                                if team1 == "":
                                    team1 = player.name + " (" + player_ranking_highest + ")" + " as " + translation["civ"][player.civ]["string"] + "\n"
                                else:
                                    team1 = team1 + player.name + " (" + player_ranking_highest + ")" + " as " + translation["civ"][player.civ]["string"] + "\n"
                            if player.team == 2:
                                if team2 == "":
                                    team2 = player.name + " (" + player_ranking_highest + ")" + " as " + translation["civ"][player.civ]["string"] + "\n"
                                else:
                                    team2 = team2 + player.name + " (" + player_ranking_highest + ")" + " as " + translation["civ"][player.civ]["string"] + "\n"

                        # Find map
                        for entry in translation["map_type"]:
                            if entry["id"] == game_object.map_type:
                                aoemap = entry["string"]
                                break

                        # Construct message
                        message = "New game on " + aoemap + ":\n\n" + team1 + "---------------- vs ---------------- \n" + team2

                        # CLI output
                        print(message)

                        # Check if its a 1v1
                        if game_object.num_players == 2:
                            # If announce_solo_games is true we send out a message
                            if announce_solo_games:
                                message_id = send_message(broadcast_channel, message)
                        # It is a team game, send message to channel
                        else:
                            message_id = send_message(broadcast_channel, message)

                        # Log to database
                        try:
                            sqlquery = "INSERT INTO logs (type, message, telegram_message_id, match_id) VALUES (\"{}\", \"{}\", \"{}\", \"{}\")".format("match", message, message_id, game_object.match_id)
                            cursor.execute(sqlquery)
                            db.commit()
                        except Exception as error:
                            print("Problem inserting last match to database! ")
                            print("Error: {}".format(error))
                else:
                    print("We have seen this game already!")

    print("-------------- Start evaluating games --------------")
    print("Games to Check:", matches_to_check)
    print("Games processed:", matches_processed)
    indexer = 0
    loop_list = list.copy(matches_to_check)
    for match_id in loop_list:
        print("Indexer:", indexer)
        print("Match id:", match_id)
        match_info = get_match_info(match_id)
        # Look for finished matches
        if match_info["finished"]:
            print("Match is finished")
            # Check if victory is announced
            check_next_match = False
            for player in match_info["players"]:
                if check_next_match:
                    break
                print("Player id to search for:", player["profile_id"])
                for user in user_list:
                    print("Taking player from list to compare:", user.profile_id)
                    if int(user.profile_id) == int(player["profile_id"]):
                        # Found user in match_info
                        print("Found user:", user.name)

                        # Check win/lost condition
                        if str(player["won"]) == "None":
                            # The game is not yet processed
                            print("Winner is not determined yet.")
                            indexer = indexer + 1

                        elif player["won"]:
                            # The game was won
                            print("The game was won!")
                            won = 1

                            # Get match message so we can construct the new message
                            try:
                                sqlquery = "SELECT message, telegram_message_id FROM logs WHERE type = 'match' AND match_id = '{}' ORDER BY `id` DESC LIMIT 1;".format(match_id)
                                cursor.execute(sqlquery)
                                records = cursor.fetchone()
                                match_message = records[0]
                                telegram_message_id = records[1]
                                game_result = "\n==> Gewonnen!! \U0001F3C6 \U0001F4AA"
                                message_edited = match_message + game_result
                                # Use edit function to post new message
                                edit_message(broadcast_channel, telegram_message_id, message_edited)
                            except Exception as error:
                                print("Problem editing Message!")
                                print("Error: {}".format(error))

                            # Log to database
                            try:
                                sqlquery = "INSERT INTO matches (match_id, won) VALUES (\"{}\", \"{}\")".format(match_id, won)
                                cursor.execute(sqlquery)
                                db.commit()
                                matches_to_check.pop(indexer)
                                print("Popped item from list!")
                                matches_processed.append(match_id)
                                print("Added item to processed list!")
                            except mysql.connector.IntegrityError as error:
                                print("Error: {}".format(error))
                                matches_to_check.pop(indexer)
                                print("Popped item from list!")
                                matches_processed.append(match_id)
                                print("Added item to processed list!")
                            except Exception as error:
                                print("Problem inserting last match to database! ")
                                print("Error: {}".format(error))
                            finally:
                                check_leaderboard_times = 10
                        else:
                            # The game was lost
                            print("A game was lost by:", user.name)
                            won = 0

                            # Get match message so we can construct the new message
                            try:
                                sqlquery = "SELECT message, telegram_message_id FROM logs WHERE type = 'match' AND match_id = '{}' ORDER BY `id` DESC LIMIT 1;".format(
                                    match_id)
                                cursor.execute(sqlquery)
                                records = cursor.fetchone()
                                match_message = records[0]
                                telegram_message_id = records[1]
                                game_result = "\n==> Verloren! \U0001F44E \U0001F44E"
                                message_edited = match_message + game_result
                                # Use edit function to post new message
                                edit_message(broadcast_channel, telegram_message_id, message_edited)
                            except Exception as error:
                                print("Problem editing Message!")
                                print("Error: {}".format(error))

                            # Log to database
                            try:
                                sqlquery = "INSERT INTO matches (match_id, won) VALUES (\"{}\", \"{}\")".format(match_id, won)
                                cursor.execute(sqlquery)
                                db.commit()
                                matches_to_check.pop(indexer)
                                print("Popped item from list!")
                                matches_processed.append(match_id)
                                print("Added item to processed list!")
                            except mysql.connector.IntegrityError as error:
                                print("Error: {}".format(error))
                                matches_to_check.pop(indexer)
                                print("Popped item from list!")
                                matches_processed.append(match_id)
                                print("Added item to processed list!")
                            except Exception as error:
                                print("Problem inserting last match to database! ")
                                print("Error: {}".format(error))
                            finally:
                                check_leaderboard_times = 10

                        print("Games to Check:", matches_to_check)
                        print("Games processed:", matches_processed)
                        print("We found the user to this game, so we break out!")
                        check_next_match = True
                        break
    print("-------------- Evaluating games done ---------------")
    amount_matches_to_check = 1

    # Check leaderboard if there was a game
    # or after a restart
    if check_leaderboard_times > 0 or restarted:
        print("-------------- Start leaderboard stuff -------------")
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
        print("-------------- Leaderboard stuff done --------------")
        restarted = False
    # Wait 60 Seconds between checks
    sleep(60)
