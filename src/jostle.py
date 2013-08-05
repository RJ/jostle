import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'build'))

import math
import psmove
import time

# Returned from movement detection stage
LOW = 1
MEDIUM = 2
HIGH = 4


class JostleState(object):
    def __init__(self, player):
        print "%s init for player %d" % (self.__class__.__name__, player.id)
        self.starttime = time.time()
        self.player = player
        self.player.move.set_rumble(0)  # cancel rumbles when changing state

    def tick(self, dt, now):
        self.player.set_color(255,255,255)
        return True


class JostleStatePending(JostleState):
    def __init__(self, player):
        super(JostleStatePending, self).__init__(player)
        player.rumble(3.0)

    def tick(self, dt, now):
        elapsed = now - self.starttime
        c = round(128 + 128 * math.sin(elapsed))
        self.player.set_color(c,c,c)

        tval = self.player.move.get_trigger()
        if tval > 0:
            self.player.set_state(JostleStateReady)


class JostleStateTimedout(JostleState):
    def tick(self, dt, now):
        self.player.set_color(0, 0, 0)


class JostleStateReady(JostleState):
    def tick(self, dt, now):
        self.player.set_color(200, 77, 0)


class JostleStateAlive(JostleState):
    def __init__(self, player):
        super(JostleStateAlive, self).__init__(player)
        self._high_threshold = 3.0
        self._medium_threshold = 1.7
        self._last_av = None
        self._warn_timeout = 0

    def _get_color(self, now, dt):
        ## Blue, if in warning state
        if self._warn_timeout > now:
            self._warn_timeout = 0
            return (0,0,255)

        return (255, 255, 255)

    def tick(self, dt, now):
        m = self.tick_detect_movement(dt, time)

        if(m == MEDIUM):  # warn user about movement..
            print "JOSTLE WARNING FOR %d" % self.player.id
            self._warn_timeout = now + 1.0

        if(m == HIGH):
            print "JOSTLE DEATH FOR %d" % self.player.id
            self.player.set_state(JostleStateDead)

        self.player.set_color(*self._get_color(now, dt))

    def tick_detect_movement(self, dt, time):
        ax, ay, az = self.player.move.get_accelerometer_frame(psmove.Frame_SecondHalf)
        av = abs(ax) + abs(ay) + abs(az)

        if(self._last_av is None):
            self._last_av = av
            return LOW

        if(av > self._high_threshold):
            return HIGH

        if(av > self._medium_threshold):
            return MEDIUM

        return LOW


class JostleStateDead(JostleState):
    def __init__(self, player):
        super(JostleStateDead, self).__init__(player)
        player.move.set_rumble(100)
        player.set_color(255, 0, 0)

    def tick(self, dt, now):
        elapsed = now - self.starttime

        if elapsed < 3.0:
            self.player.move.set_rumble(0)

        if elapsed < 5.0:
            self.player.set_color(255, 0, 0)
        else:
            self.player.set_color(0, 0, 0)


class JostlePlayer:
    def __init__(self, id):
        self.id = id
        self._now = 0
        self._last_av = None
        print "JostlePlayer(%d) inited" % id
        self.move = psmove.PSMove(id)
        if(not self.move.has_calibration()):
            raise Exception("No calibration for controller %d" % id)
        self.set_state(JostleStatePending)

    def set_state(self, newc):
        print "state --> %s" % (newc.__name__)
        self.state = newc(self)

    def set_color(self, r, g, b):
        self._r = int(min(255,max(0,round(r))))
        self._g = int(min(255,max(0,round(g))))
        self._b = int(min(255,max(0,round(b))))
        self.move.set_leds(self._r, self._g, self._b)

    def is_dead(self):
        return self.state.__class__.__name__ == "JostleStateDead"

    def rumble(self, msecs):
        if(msecs < 1):
            raise Exception("Pass a msec value > 0")
        self.rumble_hp = msecs
        self.move.set_rumble(100)

    def rainbow(self, msecs):
        self._led_setter = self._set_rainbow

    def _set_rainbow(self, dt):
        if self._now % 10 != 0:
            return;
        r = int(128 + 128 * math.sin(dt))
        self.set_color(r, 255 - r, 0)

    def tick(self, dt, now):
        self._now = now

        if self.move.poll():
            self.state.tick(dt, now)

        ## Update rumble settings
        if(self.rumble_hp > 0):
            self.rumble_hp = max(0, self.rumble_hp - dt)
            if(self.rumble_hp == 0):
                self.move.set_rumble(0)

        ## This also prods the move controller to apply rumble settings etc
        self.move.update_leds()
        return True


STATE_INIT = 1
STATE_PLAYING = 2
STATE_ENDING = 4

class JostleGame:

    def __init__(self, gameid):
        self.gameid = gameid
        self.players = [JostlePlayer(x) for x in range(psmove.count_connected())]
        self.readyplayers = []
        print "Game initializing with %d controllers detected" % (len(self.players), )
        self.starttime = time.time()
        self.lasttime = self.starttime
        self.timer = 0
        self.join_duration = 7.0
        t,a,d = self.count_players()
        print "Total players: %d, alive: %d, dead: %d" % (t, a, d)
        self.state = STATE_INIT

    def count_players(self):
        alive = 0
        dead = 0
        total = 0
        for p in self.players:
            total = total + 1
            if p.is_dead():
                dead = dead + 1
            else:
                alive = alive + 1
        return (total, alive, dead)

    def tick(self):
        self.now = time.time()
        self.dt = self.now - self.lasttime
        self.timer = self.timer + self.dt
        self.lasttime = self.now

        #if totplayers > 1 and aliveplayers == 1:  ## someone won
        #    print "WINNER!!!!!!!!!"
#
#            return False
        if self.state == STATE_INIT:
            for p in self.players:
                p.tick(self.dt, self.now)
                st = p.state.__class__
                if st == JostleStateReady:
                    continue
                if self.timer > self.join_duration:
                    print "Setting timedout for %d which was in state %r" % (p.id, st.__name__)
                    p.set_state(JostleStateTimedout)

            ## Check if all players ready
            self.readyplayers = [ p for p in self.players if p.state.__class__ == JostleStateReady ]
            if(self.timer > self.join_duration or len(self.readyplayers) == len(self.players)):
                print "Starting game with %d players" % len(self.readyplayers)
                self.state = STATE_PLAYING
                for p in self.readyplayers:
                    p.set_state(JostleStateAlive)

        if self.state == STATE_PLAYING:
            for p in self.readyplayers:
                p.tick(self.dt, self.now)
            # Check winning conditions
            totplayers, aliveplayers, deadplayers = self.count_players()
            if aliveplayers == 1:
                winner = None
                for p in self.readyplayers:
                    if p.__class__.__name__ == JostleStateAlive:
                        winner = p
                        break
                print "Winner detected!!! id: %d" % winner.id
                self.state = STATE_ENDING

        if self.state == STATE_ENDING:
            for p in self.readyplayers:
                p.tick(self.dt, self.now)
            return True



gid = 0
while True:
    gid = gid + 1
    g = JostleGame(gid)
    while True:
        g.tick()
