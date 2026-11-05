import minqlxtended
import time
import re

_FLAG_TOUCH_RE = re.compile(r"print ['\"](.*?) got the (BLUE|RED) flag!")
_FLAG_CAP_RE = re.compile(r"CAPTURED the flag!\^7 \((.+?) (?:held for|captured in) (\d+:\d+\.\d+)")


class mapstats(minqlxtended.Plugin):

    def __init__(self):
        self.add_hook("stats", self.handle_stats)
        self.add_hook("chat", self.handle_chat)
        self.add_hook("map", self.handle_map)
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("console_print", self.handle_console_print)
        self.add_hook("round_start", self.handle_round_start)

        self.weapons = ["PLASMA", "ROCKET", "PROXMINE", "RAILGUN", "CHAINGUN", "NAILGUN",
                        "GRENADE", "LIGHTNING", "SHOTGUN", "MACHINEGUN", "HMG", "BFG", "GAUNTLET"]
        self.world_death_types = ["UNKNOWN", "WATER", "SLIME", "LAVA", "CRUSH", "FALLING",
                                  "TRIGGER_HURT", "HURT"]
        self._reset_stats()

    def _reset_stats(self):
        self.best_kpm_names = []
        self.best_kpm = 0

        self.best_kd_names = []
        self.best_kd = 0

        self.most_damage_names = []
        self.most_damage = 0

        self.longest_spree_names = []
        self.longest_spree = 0

        self.best_rail_accuracy_names = []
        self.best_rail_accuracy = 0
        self.best_rail_hits = 0
        self.best_rail_shots = 0

        self.most_nade_kills_names = []
        self.most_nade_kills = 0

        self.most_pummels_names = []
        self.most_pummels = 0

        self.most_dmg_taken_names = []
        self.most_dmg_taken = 0

        self.world_death_stats = {}
        self.most_world_deaths_names = []
        self.most_world_deaths = 0

        self.most_dmg_per_kill_names = []
        self.most_dmg_per_kill = 0

        self.most_lines_of_chat_stats = {}
        self.most_lines_of_chat_names = []
        self.most_lines_of_chat = 0

        self.player_data = {}  # name -> full PLAYER_STATS DATA dict

        self.flag_touches = {}  # name -> touch count
        self._flags_touched_this_round = set()  # which flag colors touched this round
        self._flag_first_toucher = {}  # flag_color -> first_toucher_name this round
        self._flag_current_carrier = {}  # flag_color -> current_carrier_name
        self.flag_captures = {}  # name -> capture count
        self.fastest_cap_time = None  # float seconds
        self.fastest_cap_names = []

    def handle_round_start(self, round_num):
        self._flags_touched_this_round = set()
        self._flag_first_toucher = {}
        self._flag_current_carrier = {}

    def handle_console_print(self, text):
        if self.game is not None:
            m = _FLAG_TOUCH_RE.search(text)
            if m:
                name = re.sub(r'(\^[0-9])+$', '', m.group(1))
                flag_color = m.group(2)
                if flag_color not in self._flags_touched_this_round:
                    self._flags_touched_this_round.add(flag_color)
                    self.flag_touches[name] = self.flag_touches.get(name, 0) + 1
                    toucher_player = next((p for p in self.players() if p.name == name), None)
                    if toucher_player is None or str(toucher_player.steam_id)[:1] != "9":
                        self._flag_first_toucher[flag_color] = name
                    minqlxtended.console_print("{} scores a touch.".format(name))
                self._flag_current_carrier[flag_color] = name
            m = _FLAG_CAP_RE.search(text)
            if m:
                name = re.sub(r'(\^[0-9])+$', '', m.group(1))
                self.flag_captures[name] = self.flag_captures.get(name, 0) + 1
                flag_color = next((c for c, carrier in self._flag_current_carrier.items() if carrier == name), None)
                if flag_color:
                    self._flag_current_carrier.pop(flag_color, None)
                time_str = m.group(2)  # e.g. "0:07.829"
                parts = time_str.split(':')
                cap_secs = int(parts[0]) * 60 + float(parts[1])
                if flag_color and self._flag_first_toucher.get(flag_color) == name:
                    if self.fastest_cap_time is None or cap_secs < self.fastest_cap_time:
                        self.fastest_cap_time = cap_secs
                        self.fastest_cap_names = [name]
                    elif cap_secs == self.fastest_cap_time and name not in self.fastest_cap_names:
                        self.fastest_cap_names.append(name)

    def handle_chat(self, player, msg, channel, recipient):
        if self.game is not None:
            if self.game.state == "in_progress" and channel == "chat" and str(player.steam_id)[:1] != "9":
                if player.name not in self.most_lines_of_chat_stats:
                    self.most_lines_of_chat_stats[player.name] = 1
                else:
                    self.most_lines_of_chat_stats[player.name] += 1

    def handle_stats(self, stats):
        if self.game is not None:
            if self.game.state == "in_progress":
                if stats['TYPE'] == "PLAYER_DEATH":
                    if stats['DATA']['VICTIM']['STEAM_ID'] != "0":  # ignore bots
                        victim_name = stats['DATA']['VICTIM']['NAME']
                        if stats['DATA']['MOD'] in self.world_death_types:
                            if victim_name not in self.world_death_stats:
                                self.world_death_stats[victim_name] = 1
                            else:
                                self.world_death_stats[victim_name] += 1

        if stats['TYPE'] == "PLAYER_STATS":
            if stats['DATA']['QUIT'] == 0 and stats['DATA']['WARMUP'] == 0:
                if stats['DATA']['PLAY_TIME'] >= 30 and stats['DATA']['STEAM_ID'] != "0":  # ignore bots
                    player_name = stats['DATA']['NAME']
                    self.player_data[player_name] = stats['DATA']

                    player_kpm = stats['DATA']['KILLS'] / (stats['DATA']['PLAY_TIME'] / 60)

                    if stats['DATA']['DEATHS'] != 0:
                        player_kd = stats['DATA']['KILLS'] / stats['DATA']['DEATHS']
                    else:
                        player_kd = stats['DATA']['KILLS']

                    player_dmg = stats['DATA']['DAMAGE']['DEALT']
                    player_longest_spree = stats['DATA']['MAX_STREAK']

                    player_rail_hits = 0
                    player_rail_shots = 0
                    if stats['DATA']['WEAPONS']['RAILGUN']['S'] >= 15:
                        player_rail_hits = stats['DATA']['WEAPONS']['RAILGUN']['H']
                        player_rail_shots = stats['DATA']['WEAPONS']['RAILGUN']['S']
                        player_rail_accuracy = 100 * (player_rail_hits / player_rail_shots)
                    else:
                        player_rail_accuracy = 0

                    player_nade_kills = stats['DATA']['WEAPONS']['GRENADE']['K']
                    player_pummels = stats['DATA']['WEAPONS']['GAUNTLET']['K']
                    player_dmg_taken = stats['DATA']['DAMAGE']['TAKEN']

                    player_dmg_per_kill = 0
                    if stats['DATA']['KILLS'] > 0:
                        player_dmg_per_kill = stats['DATA']['DAMAGE']['DEALT'] / stats['DATA']['KILLS']

                    if not self.best_kpm_names:
                        self.best_kpm_names = [player_name]
                        self.best_kpm = player_kpm
                    elif player_kpm > self.best_kpm:
                        self.best_kpm_names = [player_name]
                        self.best_kpm = player_kpm
                    elif player_kpm == self.best_kpm:
                        self.best_kpm_names.append(player_name)

                    if not self.best_kd_names:
                        self.best_kd_names = [player_name]
                        self.best_kd = player_kd
                    elif player_kd > self.best_kd:
                        self.best_kd_names = [player_name]
                        self.best_kd = player_kd
                    elif player_kd == self.best_kd:
                        self.best_kd_names.append(player_name)

                    if not self.most_damage_names:
                        self.most_damage_names = [player_name]
                        self.most_damage = player_dmg
                    elif player_dmg > self.most_damage:
                        self.most_damage_names = [player_name]
                        self.most_damage = player_dmg
                    elif player_dmg == self.most_damage:
                        self.most_damage_names.append(player_name)

                    if not self.longest_spree:
                        self.longest_spree_names = [player_name]
                        self.longest_spree = player_longest_spree
                    elif player_longest_spree > self.longest_spree:
                        self.longest_spree_names = [player_name]
                        self.longest_spree = player_longest_spree
                    elif player_longest_spree == self.longest_spree:
                        self.longest_spree_names.append(player_name)

                    if not self.best_rail_accuracy_names:
                        self.best_rail_accuracy_names = [player_name]
                        self.best_rail_accuracy = player_rail_accuracy
                        self.best_rail_hits = player_rail_hits
                        self.best_rail_shots = player_rail_shots
                    elif player_rail_accuracy > self.best_rail_accuracy:
                        self.best_rail_accuracy_names = [player_name]
                        self.best_rail_accuracy = player_rail_accuracy
                        self.best_rail_hits = player_rail_hits
                        self.best_rail_shots = player_rail_shots
                    elif player_rail_accuracy == self.best_rail_accuracy:
                        self.best_rail_accuracy_names.append(player_name)

                    if not self.most_nade_kills_names:
                        self.most_nade_kills_names = [player_name]
                        self.most_nade_kills = player_nade_kills
                    elif player_nade_kills > self.most_nade_kills:
                        self.most_nade_kills_names = [player_name]
                        self.most_nade_kills = player_nade_kills
                    elif player_nade_kills == self.most_nade_kills:
                        self.most_nade_kills_names.append(player_name)

                    if not self.most_pummels_names:
                        self.most_pummels_names = [player_name]
                        self.most_pummels = player_pummels
                    elif player_pummels > self.most_pummels:
                        self.most_pummels_names = [player_name]
                        self.most_pummels = player_pummels
                    elif player_pummels == self.most_pummels:
                        self.most_pummels_names.append(player_name)

                    if not self.most_dmg_taken_names:
                        self.most_dmg_taken_names = [player_name]
                        self.most_dmg_taken = player_dmg_taken
                    elif player_dmg_taken > self.most_dmg_taken:
                        self.most_dmg_taken_names = [player_name]
                        self.most_dmg_taken = player_dmg_taken
                    elif player_dmg_taken == self.most_dmg_taken:
                        self.most_dmg_taken_names.append(player_name)

                    if not self.most_dmg_per_kill_names:
                        self.most_dmg_per_kill_names = [player_name]
                        self.most_dmg_per_kill = player_dmg_per_kill
                    elif player_dmg_per_kill > self.most_dmg_per_kill:
                        self.most_dmg_per_kill_names = [player_name]
                        self.most_dmg_per_kill = player_dmg_per_kill
                    elif player_dmg_per_kill == self.most_dmg_per_kill:
                        self.most_dmg_per_kill_names.append(player_name)

    @minqlxtended.delay(2)
    @minqlxtended.thread
    def handle_game_end(self, aborted):
        if aborted:
            return
        self.msg("^5***MAPSTATS***")
        if not self.best_kpm:
            return

        # Per-player stats + accuracy in uberstats style
        for i, (pname, pd) in enumerate(sorted(self.player_data.items(),
                                               key=lambda x: x[1]['KILLS'], reverse=True)):
            mins = int(pd['PLAY_TIME'] / 60)
            kd_str = "{}/{}".format(pd['KILLS'], pd['DEATHS'])
            self.msg("^2{} - ^3Name: ^7{} ^3- K/D: ^7{} ^3- DMG: ^7{} ^3- TAKEN: ^7{} ^3- TIME: ^7{}m".format(
                i + 1, pname, kd_str,
                pd['DAMAGE']['DEALT'], pd['DAMAGE']['TAKEN'], mins))
            accuracy_output = "^2ACCURACY:"
            for wpn in self.weapons:
                shots = pd['WEAPONS'][wpn]['S']
                hits  = pd['WEAPONS'][wpn]['H']
                if shots > 0:
                    accuracy = 100 * (hits / shots) if hits > 0 else 0.00
                    accuracy_output += " - ^3{}: ^1{:0.2f}".format(wpn, accuracy)
            self.msg(accuracy_output)

        stats_output = "^1KILL MACHINE: "
        for i, player_name in enumerate(self.best_kpm_names):
            stats_output += "^7" + player_name
            if len(self.best_kpm_names) > 1 and len(self.best_kpm_names) - 1 != i:
                stats_output += ", "
        stats_output += "^2 - {:0.2f} frags/min".format(self.best_kpm)
        self.msg(stats_output)

        stats_output = "^1BEST COUNTERSTRIKE PLAYER: "
        for i, player_name in enumerate(self.best_kd_names):
            stats_output += "^7" + player_name
            if len(self.best_kd_names) > 1 and len(self.best_kd_names) - 1 != i:
                stats_output += ", "
        stats_output += "^2 - {:0.2f} K/D ratio".format(self.best_kd)
        self.msg(stats_output)

        stats_output = "^1DESTRUCTICATOR: "
        for i, player_name in enumerate(self.most_damage_names):
            stats_output += "^7" + player_name
            if len(self.most_damage_names) > 1 and len(self.most_damage_names) - 1 != i:
                stats_output += ", "
        stats_output += "^2 - {:,} dmg given".format(self.most_damage)
        self.msg(stats_output)

        time.sleep(3)

        if self.longest_spree > 1:
            stats_output = "^1RAMBO: "
            for i, player_name in enumerate(self.longest_spree_names):
                stats_output += "^7" + player_name
                if len(self.longest_spree_names) > 1 and len(self.longest_spree_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {} kill streak".format(self.longest_spree)
            self.msg(stats_output)

        if self.best_rail_accuracy > 0:
            stats_output = "^1LASER EYES: "
            for i, player_name in enumerate(self.best_rail_accuracy_names):
                stats_output += "^7" + player_name
                if len(self.best_rail_accuracy_names) > 1 and len(self.best_rail_accuracy_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {:0.2f} percent rail accuracy ({} hits / {} shots)".format(
                self.best_rail_accuracy, self.best_rail_hits, self.best_rail_shots)
            self.msg(stats_output)

        if self.most_nade_kills > 0:
            stats_output = "^3PINEAPPLE POWER: "
            for i, player_name in enumerate(self.most_nade_kills_names):
                stats_output += "^7" + player_name
                if len(self.most_nade_kills_names) > 1 and len(self.most_nade_kills_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {} grenade frags".format(self.most_nade_kills)
            self.msg(stats_output)

        time.sleep(2)

        if self.most_pummels > 0:
            stats_output = "^1PUMMEL LORD: "
            for i, player_name in enumerate(self.most_pummels_names):
                stats_output += "^7" + player_name
                if len(self.most_pummels_names) > 1 and len(self.most_pummels_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {} pummels".format(self.most_pummels)
            self.msg(stats_output)

        stats_output = "^6BIGGEST PINCUSHION: "
        for i, player_name in enumerate(self.most_dmg_taken_names):
            stats_output += "^7" + player_name
            if len(self.most_dmg_taken_names) > 1 and len(self.most_dmg_taken_names) - 1 != i:
                stats_output += ", "
        stats_output += "^2 - {:,} ^6dmg taken".format(self.most_dmg_taken)
        self.msg(stats_output)

        stats_output = "^6CLUMSIEST FOOL: "
        for name, world_deaths in self.world_death_stats.items():
            if not self.most_world_deaths_names:
                self.most_world_deaths_names = [name]
                self.most_world_deaths = world_deaths
            elif world_deaths > self.most_world_deaths:
                self.most_world_deaths_names = [name]
                self.most_world_deaths = world_deaths
            elif world_deaths == self.most_world_deaths:
                self.most_world_deaths_names.append(name)

        if self.most_world_deaths > 0:
            for i, player_name in enumerate(self.most_world_deaths_names):
                stats_output += "^7" + player_name
                if len(self.most_world_deaths_names) > 1 and len(self.most_world_deaths_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {:,} deaths by world".format(self.most_world_deaths)
            self.msg(stats_output)

        time.sleep(2)

        if self.game and self.game.type not in ["Duel", "Instagib"]:
            stats_output = "^6GOOD SAMARITAN: "
            for i, player_name in enumerate(self.most_dmg_per_kill_names):
                stats_output += "^7" + player_name
                if len(self.most_dmg_per_kill_names) > 1 and len(self.most_dmg_per_kill_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {:0.2f} damage per frag".format(self.most_dmg_per_kill)
            self.msg(stats_output)

        stats_output = "^6BIGGEST CHATTERBOX: "
        for name, lines_of_chat in self.most_lines_of_chat_stats.items():
            if not self.most_lines_of_chat_names:
                self.most_lines_of_chat_names = [name]
                self.most_lines_of_chat = lines_of_chat
            elif lines_of_chat > self.most_lines_of_chat:
                self.most_lines_of_chat_names = [name]
                self.most_lines_of_chat = lines_of_chat
            elif lines_of_chat == self.most_lines_of_chat:
                self.most_lines_of_chat_names.append(name)

        if self.most_lines_of_chat > 0:
            for i, player_name in enumerate(self.most_lines_of_chat_names):
                stats_output += "^7" + player_name
                if len(self.most_lines_of_chat_names) > 1 and len(self.most_lines_of_chat_names) - 1 != i:
                    stats_output += ", "
            stats_output += "^2 - {} lines of chat".format(self.most_lines_of_chat)
            self.msg(stats_output)

        # filter flag_touches to human players only (player_data excludes bots)
        if self.game and self.game.type_short in ["ad", "ctf"]:
            human_touches = {n: c for n, c in self.flag_touches.items() if n in self.player_data}
            if human_touches:
                top_name = max(human_touches, key=human_touches.get)
                top_count = human_touches[top_name]
                touchers = [n for n, c in human_touches.items() if c == top_count]
                stats_output = "^2THE TOUCHER: "
                for i, player_name in enumerate(touchers):
                    stats_output += "^7" + player_name
                    if len(touchers) > 1 and len(touchers) - 1 != i:
                        stats_output += ", "
                stats_output += "^2 - {} flag touches".format(top_count)
                self.msg(stats_output)

            human_caps = {n: c for n, c in self.flag_captures.items() if n in self.player_data}
            if human_caps:
                top_count = max(human_caps.values())
                cappers = [n for n, c in human_caps.items() if c == top_count]
                stats_output = "^2CAPPIN' CAVEMAN!!!: "
                for i, player_name in enumerate(cappers):
                    stats_output += "^7" + player_name
                    if len(cappers) > 1 and len(cappers) - 1 != i:
                        stats_output += ", "
                stats_output += "^2 - {} flag capture{}".format(top_count, "s" if top_count != 1 else "")
                self.msg(stats_output)

            human_roadrunners = [n for n in self.fastest_cap_names if n in self.player_data]
            if self.fastest_cap_time is not None and human_roadrunners:
                mins = int(self.fastest_cap_time // 60)
                secs = self.fastest_cap_time % 60
                time_fmt = "{}:{:06.3f}".format(mins, secs)
                stats_output = "^2ROADRUNNER: "
                for i, player_name in enumerate(human_roadrunners):
                    stats_output += "^7" + player_name
                    if len(human_roadrunners) > 1 and len(human_roadrunners) - 1 != i:
                        stats_output += ", "
                stats_output += "^2 - fastest cap in {}".format(time_fmt)
                self.msg(stats_output)
    @minqlxtended.delay(10)
    def handle_map(self, mapname, factory):
        self._reset_stats()
