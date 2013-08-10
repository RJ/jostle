#!/usr/bin/env python
import sys
import os
# TODO path to psmove stuff
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'build'))

import math
import psmove
import time


class JostleState(object):
    def __init__(self, player):
        print "[%d] -> %s" % (player.id, self.__class__.__name__)
        self.starttime = time.time()
        self.player = player
        self.player.move.set_rumble(0)  # cancel rumbles when changing state

    def tick(self, dt, now):
        self.player.set_color(255, 255, 255)
        return True


class JostleStatePending(JostleState):
    def __init__(self, player):
        super(JostleStatePending, self).__init__(player)
        player.rumble(1.5)

    def tick(self, dt, now):
        # make the light breathe while in a pending state
        c = math.sin(now) * 115 + 140
        self.player.set_color(c * 0.3, c, c * 0.3)

        tval = self.player.move.get_trigger()
        if tval > 0:
            self.player.set_state(JostleStateReady)


class JostleStateTimedout(JostleState):
    def tick(self, dt, now):
        self.player.set_color(0, 0, 0)


# Do nothing state
class JostleStateNothing(JostleState):
    def tick(self, dt, now):
        pass


class JostleStateReady(JostleState):
    def tick(self, dt, now):
        # Go green for ready state, until game has enough players
        self.player.set_color(0, 255, 0)


class JostleStateAlive(JostleState):
    # Returned from movement detection stage
    LOW = 1
    MEDIUM = 2
    HIGH = 4

    def __init__(self, player):
        super(JostleStateAlive, self).__init__(player)
        self._high_threshold = 3.0
        self._medium_threshold = 1.7
        self._warn_timeout = 0

    def _get_color(self, now, dt):
        # Blue, if in warning state
        if self._warn_timeout > now:
            self._warn_timeout = 0
            return (255, 0, 0)

        # Rainbow mode if celebrating a win
        if self.player.winner:
            colors = [
                (255, 0, 0),
                (0, 255, 0),
                (0, 0, 255),
                (0, 255, 255),
                (255, 0, 255),
                (255, 255, 0),
            ]
            inc = now % 1
            x = inc * inc

            def blend(a, b):
                def mix(idx):
                    return int(a[idx] * (1. - x) + b[idx] * float(x))
                return (mix(0), mix(1), mix(2))
            col1 = int(now % len(colors))
            col2 = int((col1 + 1) % len(colors))
            return blend(colors[col1], colors[col2])

        # Solid white if just playing normally
        return (255, 255, 255)

    def tick(self, dt, now):
        self.player.set_color(*self._get_color(now, dt))

        if not self.player.winner:
            m = self.tick_detect_movement(dt, time)

            if(m == self.__class__.MEDIUM):  # warn user about movement..
                #print "JOSTLE WARNING FOR %d" % self.player.id
                self._warn_timeout = now + 0.3

            if(m == self.__class__.HIGH):
                #print "JOSTLE DEATH FOR %d" % self.player.id
                self.player.set_state(JostleStateDead)

    def tick_detect_movement(self, dt, time):
        ax, ay, az = self.player.move.get_accelerometer_frame(psmove.Frame_SecondHalf)
        av = abs(ax) + abs(ay) + abs(az)

        if(av > self._high_threshold):
            return self.__class__.HIGH

        if(av > self._medium_threshold):
            return self.__class__.MEDIUM

        return self.__class__.LOW


class JostleStateDead(JostleState):
    def __init__(self, player):
        super(JostleStateDead, self).__init__(player)
        player.rumble(3)
        player.set_color(255, 0, 0)

    def tick(self, dt, now):
        elapsed = now - self.starttime
        # red for 5 seconds
        if elapsed < 5.0:
            self.player.set_color(255, 0, 0)
        # fade out the red
        elif elapsed < 7.55:
            delta = 255 - int((elapsed - 5) * 100)
            self.player.set_color(delta, 0, 0)
        else:
            self.player.set_color(0, 0, 0)


class JostlePlayer:
    def __init__(self, id):
        self.id = id
        print "JostlePlayer(%d) inited" % id
        self.move = psmove.PSMove(id)
        if(not self.move.has_calibration()):
            raise Exception("No calibration for controller %d" % id)
        self.reset()

    def reset(self):
        self._now = 0
        self.winner = False
        self.set_state(JostleStatePending)

    def set_state(self, newc):
        self.state = newc(self)

    def set_winner(self):
        self.winner = True

    def set_color(self, r, g, b):
        self._r = int(min(255, max(0, round(r))))
        self._g = int(min(255, max(0, round(g))))
        self._b = int(min(255, max(0, round(b))))
        self.move.set_leds(self._r, self._g, self._b)

    def is_dead(self):
        return self.state.__class__ == JostleStateDead

    def rumble(self, secs):
        self.rumble_expiry = time.time() + secs
        self.move.set_rumble(100)

    def tick(self, dt, now):
        self._now = now

        if self.move.poll():
            self.state.tick(dt, now)

        if(self.rumble_expiry != 0 and self.rumble_expiry > now):
            self.rumble_expiry = 0
            self.move.set_rumble(0)

        ## This also prods the move controller to apply rumble settings etc
        self.move.update_leds()
        return True


class JostleGame:

    INIT = 1
    STARTING = 2
    PLAYING = 3
    ENDING = 4

    def __init__(self, gameid):
        self.gameid = gameid
        self.players = [JostlePlayer(x) for x in range(psmove.count_connected())]
        print "Game %d initializing with %d controllers" % (gameid, len(self.players), )
        self.starttime = time.time()
        self.lasttime = self.starttime
        self.join_duration = 20
        self.reset()
        self.state = self.__class__.INIT

    def reset(self):
        self.gameplayers = []
        self.aliveplayers = []
        self.timer = 0
        self.ending_timeout = 0

    def tick(self):
        self.now = time.time()
        self.dt = self.now - self.lasttime
        self.timer = self.timer + self.dt
        self.lasttime = self.now

        if self.state == self.__class__.INIT:
            numready = 0

            timeready = False
            if self.timer > self.join_duration:
                # game is ready to start
                timeready = True

            for p in self.players:
                p.tick(self.dt, self.now)
                st = p.state.__class__
                if st == JostleStateReady:
                    numready = numready + 1
                    continue
                # timeout players who haven't joined yet, ie they miss this round
                if timeready and numready > 1:
                    print "Setting timedout for %d which was in state %r" % (p.id, st.__name__)
                    p.set_state(JostleStateTimedout)

            if timeready and numready > 1 or numready == len(self.players):
                ## Start the game
                self.gameplayers = [p for p in self.players if p.state.__class__ == JostleStateReady]
                print "************************************"
                print "Starting game with %d players" % numready
                print "************************************"
                self.state = self.__class__.STARTING
                self.starting_expiry = time.time() + 2
                for p in self.gameplayers:
                    p.set_state(JostleStateNothing)

        if self.state == self.__class__.STARTING:
            if time.time() > self.starting_expiry:
                self.state = self.__class__.PLAYING
                for p in self.gameplayers:
                    p.set_state(JostleStateAlive)
            else:
                pc = (2 - (self.starting_expiry - time.time())) / 2
                c = int(pc * pc * pc * 255)
                for p in self.players:
                    p.set_color(c, 255, c)
                    p.tick(self.dt, self.now)

        if self.state == self.__class__.PLAYING:
            # Update state of all players
            for p in self.gameplayers:
                p.tick(self.dt, self.now)

            # Check winning conditions
            ap = [player for player in self.gameplayers if not player.is_dead()]
            if len(ap) != len(self.aliveplayers):
                print "*** Remaining players: %d" % len(ap)
            self.aliveplayers = ap

            if len(self.aliveplayers) == 1:
                winner = self.aliveplayers[0]
                winner.set_winner()
                print "*** WINNER DETECTED id: %d" % winner.id
                self.ending_timeout = time.time() + 15
                self.state = self.__class__.ENDING

        if self.state == self.__class__.ENDING:
            if time.time() > self.ending_timeout:
                print "*** GAME RESTARTING"
                self.reset()
                for p in self.players:
                    p.reset()
                self.state = self.__class__.INIT
            else:
                # Still waiting for celebrations to finish
                for p in self.players:
                    p.tick(self.dt, self.now)
            return True


ticks_per_sec = 60
game_id = 0

while True:
    game_id += 1
    game = JostleGame(game_id)

    oldnow = time.time()
    while True:
        now = time.time()
        sleeptime = 1.0 / ticks_per_sec - (now - oldnow)
        if sleeptime > 0:
            time.sleep(sleeptime)
        oldnow = now

        game.tick()
