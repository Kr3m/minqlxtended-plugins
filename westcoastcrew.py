# coding: utf8
# minqlx - A Quake Live server administrator bot.
# Copyright (C) 2015 Mino <mino@minomino.org>

# This file is part of minqlxtended.

# minqlx is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# minqlx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with minqlxtended. If not, see <http://www.gnu.org/licenses/>.

import minqlxtended
import random
import time
import re

from minqlxtended.database import Redis
_re_ = {}


def add_sound(key, regex, path):
    _re_[key] = [re.compile(regex, flags=re.IGNORECASE), path]

add_sound("turple", r"turple", "sound/westcoastcrew/turpled.ogg")
add_sound("cant touch this", r"^can'?t touch this\W?$", "sound/westcoastcrew/CantTouchThis.ogg")
add_sound("ay caramba", r"^ay caramba", "sound/westcoastcrew/aycaramba.ogg")
add_sound("ballin", r"^ballin\W?$", "sound/westcoastcrew/ballin.ogg")
add_sound("bigpippin", r"^bigpippin\W?$", "sound/westcoastcrew/bigpippin.ogg")
add_sound("big whoop", r"(?:big woop|big whoop)", "sound/westcoastcrew/bigwhoop.ogg")
add_sound("did i do that", r"^did i do that*", "sound/westcoastcrew/dididothat.ogg")
add_sound("did i do that 2", r"^DDDid i do that*", "sound/westcoastcrew/dididothat2.ogg")
add_sound("doomed", r"(?:doomed|doom'?d)", "sound/westcoastcrew/doomed.ogg")
add_sound("ez", r"(?:^ez|^easy$|so easy|that was easy|that was ez)", "sound/westcoastcrew/ez.ogg")
add_sound("Gay", r"^Gay\W?$", "sound/westcoastcrew/Gay.ogg")
add_sound("haha", r"^haha\W?$", "sound/westcoastcrew/haha.ogg")
add_sound("introtoo", r"^introtoo\W?$", "sound/westcoastcrew/intro2.ogg")
add_sound("jsss", r"^jsss\W?$", "sound/westcoastcrew/jsss.ogg")
add_sound("opinion", r"(?:opinion|well, you know, that's*)", "sound/westcoastcrew/opinion.ogg")
add_sound("rockyouguitar", r"^rockyouguitar\W?$", "sound/westcoastcrew/RockYouGuitar.ogg")
add_sound("snort", r"^snort\W?$", "sound/westcoastcrew/snort.ogg")
add_sound("SNpete", r"^SNpete\W?$", "sound/westcoastcrew/SNpete.ogg")
add_sound("SNpete2", r"(?:snpete2|chick chicky boom)", "sound/westcoastcrew/SNpete2.ogg")
add_sound("bender", r"^bender\W?$", "sound/westcoastcrew/bender.ogg")
add_sound("2ez", r"(?:2ez|too easy)", "sound/westcoastcrew/2ez.ogg")
add_sound("bender", r"^bender\W?$", "sound/westcoastcrew/bender.ogg")
add_sound("reflexes", r"(?:reflexes|it'?s all in the reflexes)", "sound/westcoastcrew/reflexes.ogg")
add_sound("rothko", r"^rothko\W?$", "sound/westcoastcrew/rothko_theme.ogg")
add_sound("bite my shiny metal ass", r"^bite my shiny metal*", "sound/westcoastcrew/bitemyshinymetalass.ogg")
add_sound("c3", r"^c3\W?$", "sound/westcoastcrew/c3.ogg")
add_sound("cthree", r"^cthree\W?$", "sound/westcoastcrew/cuttingedge.ogg")
add_sound("cann", r"^cann\W?$", "sound/westcoastcrew/cann.ogg")
add_sound("clr", r"^clr\W?$", "sound/westcoastcrew/clr.ogg")
add_sound("hahahaha", r"^hahahaha\W?$", "sound/westcoastcrew/hahahaha.ogg")
add_sound("isabadmutha", r"^isabadmutha\W?$", "sound/westcoastcrew/isabadmutha.ogg")
add_sound("shaft", r"^shaft\W?$", "sound/westcoastcrew/shaft.ogg")
add_sound("nooo", r"^nooo\W?$", "sound/westcoastcrew/Nooo.ogg")
add_sound("oh no", r"^oh no\W?$", "sound/westcoastcrew/OhNo.ogg")
add_sound("teamwork", r"teamwork", "sound/westcoastcrew/Teamwork.ogg")
add_sound("retard", r"retard", "sound/westcoastcrew/Retard.ogg")
add_sound("chaching", r"(?:\$|€|£|chaching)", "sound/misc/chaching.ogg")
add_sound("bofumballs", r"bofumb*", "sound/westcoastcrew/bofumballs.ogg")
add_sound("makaveli", r"(?:mak$|makaveli)", "sound/westcoastcrew/makaveli.ogg")
add_sound("rothkoo", r"^rothkoo\W?$", "sound/westcoastcrew/rothko.ogg")
add_sound("oshikia", r"^oshikia\W?$", "sound/westcoastcrew/oshikia.ogg")
add_sound("qqaaq", r"^qqaaq*", "sound/westcoastcrew/qqaaq.ogg")
add_sound("qaaq", r"^qaaq*", "sound/westcoastcrew/qaaq.ogg")
add_sound("muthafucka", r"^muthafucka*", "sound/westcoastcrew/muthafucka.ogg")
add_sound("fuckin bitch", r"^fuckin bitch*", "sound/westcoastcrew/fuckinbitch.ogg")
add_sound("chocosaurus", r"^chocosauruse*", "sound/westcoastcrew/chocosaurus.ogg")
add_sound("los", r"^los$", "sound/westcoastcrew/los.ogg")
add_sound("get outta here", r"^get outta here*", "sound/westcoastcrew/getouttahere.ogg")
add_sound("nonsense", r"^nonsense*", "sound/westcoastcrew/nonsense.ogg")
add_sound("counting on you", r"^counting on you*", "sound/westcoastcrew/countingonyou.ogg")
add_sound("damn im good", r"^damn i'?m good*", "sound/westcoastcrew/damnimgood.ogg")
add_sound("really", r"^really*", "sound/westcoastcrew/really.ogg")
add_sound("hehehe", r"^hehehe*", "sound/westcoastcrew/hehehe.ogg")
add_sound("lol loser", r"(?:lol loser*|loser*)", "sound/westcoastcrew/lolloser.ogg")
add_sound("die motherfucker", r"^die motherfucker*", "sound/westcoastcrew/diemotherfucker.ogg")
add_sound("die mothafuckas", r"^die mothafuckas*", "sound/westcoastcrew/diemothafuckas.ogg")
add_sound("die already", r"^die already$", "sound/westcoastcrew/diealready.ogg")
add_sound("give up and die", r"^give up and die*", "sound/westcoastcrew/giveupanddie.ogg")
add_sound("die", r"^die$", "sound/westcoastcrew/die.ogg")
add_sound("im stephan", r"^i'?m stephan*", "sound/westcoastcrew/imstephan.ogg")
add_sound("nonononono", r"^no no no no no*", "sound/westcoastcrew/nonononono.ogg")
add_sound("clever girl", r"^clever girl", "sound/westcoastcrew/clevergirl.ogg")
add_sound("stfu", r"^stfu*", "sound/westcoastcrew/stfu.ogg")
add_sound("what did you do", r"^what did you do*", "sound/westcoastcrew/whatdidyoudo.ogg")
add_sound("look what you did", r"^look what you did*", "sound/westcoastcrew/lookwhatyoudid.ogg")
add_sound("drunk", r"(?:^drunk|always smokin' blunts|gettin' drunk)", "sound/westcoastcrew/drunk.ogg")
add_sound("gibbles", r"^gibbles\W?$", "sound/westcoastcrew/gibbles.ogg")
add_sound("rugged", r"(?:rugged\W?$|like a rock)", "sound/westcoastcrew/rugged.ogg")
add_sound("fox", r"^fox\W?$", "sound/westcoastcrew/fox.ogg")
add_sound("dr1nya", r"^dr1nya\W?$", "sound/westcoastcrew/dr1nya.ogg")
add_sound("vks", r"(?:^vks$|bow$)", "sound/westcoastcrew/vks.ogg")
add_sound("obliv", r"(?:obliv$|oblivious)", "sound/westcoastcrew/obliv2.ogg")
add_sound("oblivion", r"oblivion", "sound/westcoastcrew/obliv.ogg")
add_sound("flush", r"flush", "sound/westcoastcrew/flush.ogg")
add_sound("shenookie", r"shenookie$", "sound/westcoastcrew/shenookies.ogg")
add_sound("shenookies cookies", r"shenookie'?s cookies$", "sound/westcoastcrew/shenook.ogg")
add_sound("campingtroll", r"(?:campingtroll|baby got back)", "sound/westcoastcrew/campingtroll.ogg")
add_sound("happy hour", r"(:?happy hour|it?'s happy hour*)", "sound/westcoastcrew/happyhour.ogg")
add_sound("baiting", r"baitin*", "sound/westcoastcrew/baiting.ogg")
add_sound("solis", r"solis$", "sound/westcoastcrew/solis.ogg")
add_sound("tustamena", r"tustamena", "sound/westcoastcrew/tustamena.ogg")
add_sound("atustamena", r"atustamena", "sound/westcoastcrew/atustamena.ogg")
add_sound("hahaha", r"hahaha$", "sound/westcoastcrew/hahaha.ogg")
add_sound("outro", r"outro", "sound/westcoastcrew/biggerlove.ogg")
add_sound("w3rd", r"w3rd", "sound/westcoastcrew/w3rd.ogg")
add_sound("unstoppable", r"unstoppable", "sound/westcoastcrew/unstoppable.ogg")
add_sound("monster kill", r"monster kill", "sound/westcoastcrew/monsterkill.ogg")
add_sound("dominating", r"dominating", "sound/westcoastcrew/dominating.ogg")
add_sound("godlike", r"godlike", "sound/westcoastcrew/godlike.ogg")
add_sound("dundun", r"(?:dun dun$|dundun$)", "sound/westcoastcrew/dundun.ogg")
add_sound("dundundun", r"(?:dun dun dun$|dundundun$)", "sound/westcoastcrew/dundundun.ogg")
add_sound("dundundundun", r"(?:dun dun dun dun$|dundundundun$)", "sound/westcoastcrew/dundundundun.ogg")
add_sound("filthy zealot", r"(?:keep the change*|filthy zealot)", "sound/westcoastcrew/filthyzealot.ogg")
add_sound("lg", r"lg", "sound/westcoastcrew/lg.ogg")
add_sound("mirai", r"mirai", "sound/westcoastcrew/mirai.ogg")
add_sound("you lose", r"you lose", "sound/westcoastcrew/youlose.ogg")
add_sound("scrub", r"scrub", "sound/westcoastcrew/scrub.ogg")
add_sound("swish", r"swish", "sound/westcoastcrew/swish.ogg")
add_sound("easy as 123", r"(?:easy as*|ABC)", "sound/westcoastcrew/easyas.ogg")
add_sound("kinraze", r"kinraze$", "sound/westcoastcrew/kinraze.ogg")
add_sound("mobil", r"mobil", "sound/westcoastcrew/mobil.ogg")
add_sound("gimme a break", r"gimme a break", "sound/westcoastcrew/gimmeabreak.ogg")
add_sound("pizza pizza", r"(?:pizza pizza|meetzah meetzah|heetzah peetzah)", "sound/westcoastcrew/meetzah.ogg")
add_sound("inspector norse", r"inspector", "sound/westcoastcrew/inspectornorse.ogg")
add_sound("kinrazed", r"kinrazed", "sound/westcoastcrew/alright.ogg")
add_sound("martin", r"martin", "sound/westcoastcrew/martin.ogg")
add_sound("bumblebee tuna", r"(?:your balls are showing|bumblebee tuna)", "sound/westcoastcrew/bumblebeetuna.ogg")
add_sound("ventt", r"ventt", "sound/westcoastcrew/v3ntt.ogg")
add_sound("littlemeezers", r"littlemeezers", "sound/westcoastcrew/pizzaguy.ogg")
add_sound("ty", r"(?:thanks|ty)", "sound/westcoastcrew/ty.ogg")
add_sound("gs", r"gs", "sound/westcoastcrew/gs.ogg")
add_sound("great shot", r"great shot", "sound/westcoastcrew/greatshot.ogg")
add_sound("thetealduck", r"thetealduck", "sound/westcoastcrew/thetealduck.ogg")
add_sound("giggs", r"giggs", "sound/westcoastcrew/giggs.ogg")
add_sound("hehe", r"hehe$", "sound/westcoastcrew/hehe.ogg")
add_sound("clear", r"clear", "sound/westcoastcrew/clr2.ogg")
add_sound("rage quit", r"rage quit", "sound/westcoastcrew/ragequit.ogg")
add_sound("im on fire", r"i'?m on fire", "sound/westcoastcrew/imonfire.ogg")
add_sound("so is your face", r"so'?s your face", "sound/westcoastcrew/soisyourface.ogg")
add_sound("jdub", r"(?:jdub|y'?all ready for this)", "sound/westcoastcrew/yallreadyforthis.ogg")
add_sound("in the zone", r"(?:in the zone|i'?m in the zone)", "sound/westcoastcrew/inthezone.ogg")
add_sound("papabalyo", r"papabalyo", "sound/westcoastcrew/papabaylo.ogg")
add_sound("boomshakalaka", r"boomshakalaka", "sound/westcoastcrew/boomshakalaka.ogg")
add_sound("facial", r"facial", "sound/westcoastcrew/facial.ogg")
add_sound("hes on fire", r"he'?s on fire", "sound/westcoastcrew/onfire.ogg")
add_sound("hes heating up", r"he'?s heating up", "sound/westcoastcrew/heatingup.ogg")
add_sound("wuyoga", r"wuyoga", "sound/westcoastcrew/wuyoga.ogg")
add_sound("feroz", r"feroz", "sound/westcoastcrew/feroz.ogg")
add_sound("biff", r"biff", "sound/westcoastcrew/biff.ogg")
add_sound("psygib", r"psygib", "sound/westcoastcrew/psygib.ogg")
add_sound("in the face", r"in the face", "sound/westcoastcrew/intheface.ogg")
add_sound("ability", r"ability", "sound/westcoastcrew/ability.ogg")
add_sound("stitch", r"stitch", "sound/westcoastcrew/stitch.ogg")
add_sound("killswitch", r"killswitch", "sound/westcoastcrew/killswitch.ogg")
add_sound("shufflenufiguess", r"shufflenufiguess", "sound/westcoastcrew/shufflenufflegus.ogg")
add_sound("elo", r"\!elo", "sound/westcoastcrew/elo.ogg")
add_sound("vacuum", r"vacuum", "sound/westcoastcrew/vacuum.ogg")
add_sound("wolf", r"wolf", "sound/westcoastcrew/wolf.ogg")
add_sound("saved", r"saved", "sound/westcoastcrew/saved.ogg")
add_sound("still feel like youre mad", r"still feel like you'?re mad", "sound/westcoastcrew/stillmad.ogg")
add_sound("its a disastah", r"(?:disast|it'?s a disast)", "sound/westcoastcrew/disastah.ogg")
add_sound("rekt", r"rekt", "sound/westcoastcrew/rekt.ogg")
add_sound("troll toll", r"troll toll", "sound/westcoastcrew/trolltoll.ogg")
add_sound("gotta pay the troll", r"gotta pay the troll", "sound/westcoastcrew/paytrolltoll.ogg")
add_sound("lets get ready to rumble", r"let'?s get ready to rumble", "sound/westcoastcrew/readytorumble.ogg")
add_sound("f3", r"f3", "sound/westcoastcrew/f3.ogg")
add_sound("look what youve done", r"look what you'?ve done", "sound/westcoastcrew/lookwhatyouvedone.ogg")
add_sound("doom", r"(?:doom$|tell me what you came here for)", "sound/westcoastcrew/intoyou.ogg")
add_sound("ooom", r"ooom", "sound/westcoastcrew/oomwhatyousay.ogg")
add_sound("and another one gone", r"and another one gone", "sound/westcoastcrew/anotheronegone.ogg")
add_sound("another one bites the dust", r"another one bites the dust", "sound/westcoastcrew/anotheronebitesthedust.ogg")
add_sound("easy come easy go", r"easy come easy go", "sound/westcoastcrew/easycomeeasygo.ogg")
add_sound("yeah baby", r"yeah baby", "sound/westcoastcrew/yeahbaby.ogg")
add_sound("hehe yeah", r"hehe yeah", "sound/westcoastcrew/heheyeah.ogg")
add_sound("dead last", r"(?:yeah,/? how'?d he finish again|dead last)", "sound/westcoastcrew/deadlast.ogg")
add_sound("skadoosh", r"skadoosh", "sound/westcoastcrew/skadoosh.ogg")
add_sound("im a motherfuckin monster", r"i'?m a motherfuckin monst", "sound/westcoastcrew/monster.ogg")
add_sound("its in the bag", r"it'?s in the bag", "sound/westcoastcrew/inthebag1.ogg")
add_sound("in the bag", r"in the bag", "sound/westcoastcrew/inthebag2.ogg")
add_sound("wow", r"wow$", "sound/westcoastcrew/wow.ogg")
add_sound("woww", r"woww", "sound/westcoastcrew/wow2.ogg")
add_sound("thats all folks", r"that'?s all folks", "sound/westcoastcrew/thatsallfolks.ogg")
add_sound("spank you", r"spank you", "sound/westcoastcrew/spankyou.ogg")
add_sound("why you litte", r"why you little", "sound/westcoastcrew/whyyoulittle.ogg")
add_sound("you can do it", r"you can do", "sound/westcoastcrew/youcandoit.ogg")
add_sound("did you miss me", r"did you miss me", "sound/westcoastcrew/missme.ogg")
add_sound("somebody stop me", r"somebody stop me", "sound/westcoastcrew/stopme.ogg")
add_sound("slime", r"slime", "sound/westcoastcrew/slime.ogg")
add_sound("waow", r"waow", "sound/westcoastcrew/waow.ogg")
add_sound("lovin it", r"lovin'? it", "sound/westcoastcrew/lovinit.ogg")
add_sound("yawn", r"yawn$", "sound/westcoastcrew/yawn.ogg")
add_sound("yawnn", r"yawnn", "sound/westcoastcrew/yawnn.ogg")

class westcoastcrew(minqlxtended.Plugin):
    database = Redis

    def __init__(self):
        super().__init__()
        self.add_hook("chat", self.handle_chat)
        self.add_command("cookies", self.cmd_cookies)
        self.last_sound = None
        self.add_command(("soundlist", "slist"), self.cmd_soundlist, client_cmd_perm=0, usage="<pagenum>")
        self.set_cvar_once("qlx_funSoundDelay", "1")


    def cmd_soundlist(self, player, msg, channel):
        """Prints a page of the sound list"""
        page = 0
        linesPerPage = 20
        totalpages = -(-len(_re_) // linesPerPage) -1  #ceil division trick to get pages for 10 items per page, -1 as 0= first.

        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        if len(msg) > 1:
            try:
                page = int(msg[1])

            except ValueError:
                player.tell("Invalid page number.")
                return minqlxtended.Return.STOP_ALL

        page = page - 1
        if page > totalpages:
            page = totalpages
        if page < 1:
            page = 0
        player.tell("^5Sound list - page {} of {}".format(page + 1, totalpages + 1))
        for key in sorted(_re_)[page * linesPerPage:page * linesPerPage + linesPerPage]:  # slice for pagination
            player.tell("   ^2{}".format(key))

    def handle_chat(self, player, msg, channel, recipient):
        if channel != "chat":
            return

        msg = self.clean_text(msg)
        for key in _re_:
        	if _re_[key][0].match(msg):
        		self.play_sound(_re_[key][1])

    def play_sound(self, path):
        if not self.last_sound:
            pass
        elif time.time() - self.last_sound < self.get_cvar("qlx_funSoundDelay", int):
            return

        self.last_sound = time.time()
        for p in self.players():
            if self.db.get_flag(p, "essentials:sounds_enabled", default=True):
                super().play_sound(path, p)

    def cmd_cookies(self, player, msg, channel):
        x = random.randint(0, 100)
        if not x:
            channel.reply("^6? ^7Here you go, {}. I baked these just for you! ^6?".format(player))
        elif x == 1:
            channel.reply("What, you thought ^6you^7 would get cookies from me, {}? Hah, think again.".format(player))
        elif x < 50:
            channel.reply("For me? Thank you, {}!".format(player))
        else:
            channel.reply("I'm out of cookies right now, {}. Sorry!".format(player))
