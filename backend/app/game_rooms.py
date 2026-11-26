import asyncio
import secrets
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool


Nickname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
Phase = Literal['lobby', 'answer', 'reveal', 'draft', 'vote', 'waiting', 'finished']
clock = time.monotonic


class RoomSettings(BaseModel):
    answer_seconds: int = Field(default=15, ge=3, le=300)
    continue_seconds: int = Field(default=10, ge=0, le=300)
    cropped: bool = False
    single_life: bool = False


class GameFilters(BaseModel):
    people: str = ''
    publishers: str = ''
    match: Literal['any', 'all', 'exact', 'subset'] = 'any'
    start: str = ''
    end: str = ''
    include_no_faces: bool = False


class JoinRoom(BaseModel):
    nickname: Nickname


class CreateRoom(JoinRoom):
    settings: RoomSettings = Field(default_factory=RoomSettings)
    filters: GameFilters = Field(default_factory=GameFilters)


class Membership(BaseModel):
    code: str
    token: str


class RoomAction(BaseModel):
    action: Literal['settings', 'start', 'restart', 'answer', 'ready', 'draft', 'cancel', 'submit', 'vote', 'finish', 'leave']
    stage: int
    settings: RoomSettings | None = None
    choice: int | None = None
    support: bool | None = None
    suggested_person_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    not_face: bool = False
    content: str = Field(default='', max_length=1000)


class Choice(BaseModel):
    id: int
    name: str


class RoomPhoto(BaseModel):
    width: int
    height: int
    image_url: str
    box: list[float]
    choices: list[Choice]


class PlayerView(BaseModel):
    id: int
    name: str
    correct: int
    wrong: int
    unanswered: int
    eliminated: bool
    online: bool
    playing: bool
    answered: bool
    ready: bool


class Proposal(BaseModel):
    suggested_name: str | None
    suggested_person_id: int | None
    not_face: bool
    content: str


class RevealedPhoto(BaseModel):
    group_id: int
    image_id: int


class ChoiceTally(BaseModel):
    choice: int | None
    count: int
    nickname: str | None


class RoomView(BaseModel):
    code: str
    version: int
    stage: int
    phase: Phase
    round: int
    host: int
    me: int
    settings: RoomSettings
    filters: GameFilters
    remaining: float | None
    players: list[PlayerView]
    photo: RoomPhoto | None
    source_photo: RevealedPhoto | None
    tallies: list[ChoiceTally] | None
    choice: int | None
    answer_name: str | None
    correct_choice: int | None
    void: bool
    proposer: int | None
    proposal: Proposal | None
    accepted: bool | None
    votes_for: int
    votes_against: int
    voted: bool
    ending: bool
    message: str


@dataclass
class Player:
    id: int
    name: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    seen: float = field(default_factory=lambda: clock())
    online: bool = True
    correct: int = 0
    wrong: int = 0
    unanswered: int = 0
    withdrawn: bool = False

    def eliminated(self, single_life):
        return single_life and (self.withdrawn or self.wrong + self.unanswered > 0)


def check(condition, message, status=409):
    if not condition:
        raise HTTPException(status, message)


class Room:
    def __init__(self, code, setup, draw):
        self.code, self.settings, self.filters, self.draw = code, setup.settings, setup.filters, draw
        self.players = {}
        self.host = self.serial = self.version = self.stage = 0
        self.phase = 'lobby'
        self.lock, self.event = asyncio.Lock(), asyncio.Event()
        self.touched = clock()
        self.reset_match()

    def reset_match(self):
        self.round = 0
        self.question = self.deadline = self.correct = self.proposer = self.proposal = self.accepted = None
        self.ending = self.void = False
        self.message = ''
        self.playing, self.ready, self.outcomes = set(), set(), {}
        self.answers, self.votes = {}, {}

    def changed(self):
        self.version += 1
        self.event.set()
        self.event = asyncio.Event()

    def enter(self, phase, seconds=None):
        self.phase = phase
        self.deadline = None if seconds is None else clock() + seconds
        self.stage += 1
        self.changed()

    def join(self, name):
        check(self.phase != 'finished' and not self.ending, '对战已经结束')
        check(not self.settings.single_life or not self.round, '一命模式开局后不能加入')
        check(len(self.players) < 12, '房间已满')
        check(all(player.name != name for player in self.players.values()), '房间内已有相同昵称')
        self.serial += 1
        player = Player(self.serial, name)
        self.players[player.id] = player
        if not self.host:
            self.host = player.id
        self.touched = clock()
        self.changed()
        return Membership(code=self.code, token=player.token)

    def online(self):
        return {player.id for player in self.players.values() if player.online}

    def survivors(self):
        return {player.id for player in self.players.values() if not player.eliminated(self.settings.single_life)}

    def presence(self, current=None):
        now = clock()
        if current:
            current.seen = self.touched = now
        for player in self.players.values():
            online = now - player.seen < 30
            if online != player.online:
                player.online = online
                self.changed()
        online = self.online()
        if online and self.host not in online:
            self.host = min(online)
            self.changed()

    async def next_question(self):
        participants = self.survivors() if self.settings.single_life else self.online()
        if self.settings.single_life and self.round and len(participants) <= 1:
            self.enter('finished')
            return
        if len(participants) < 2:
            self.message = '等待至少两位玩家在线'
            self.enter('waiting')
            return
        try:
            question = await run_in_threadpool(self.draw, self.filters, self.question)
        except HTTPException as error:
            self.message = str(error.detail)
            self.enter('waiting')
            return
        self.question, self.message = question, ''
        self.round += 1
        self.playing, self.answers, self.ready, self.outcomes = participants, {}, set(), {}
        self.proposer = self.proposal = self.accepted = None
        self.votes, self.void = {}, False
        self.enter('answer', self.settings.answer_seconds)

    def score(self):
        person = self.question['face']['person_id']
        if self.accepted:
            person = self.proposal.suggested_person_id
        self.void = person is None
        self.correct = next((item['id'] for item in self.question['choices'] if item['id'] == person), None)
        for key in self.playing:
            player = self.players[key]
            previous = self.outcomes.pop(key, None)
            if previous:
                setattr(player, previous, getattr(player, previous) - 1)
            if not self.void:
                outcome = 'unanswered' if key not in self.answers else 'correct' if self.answers[key] == self.correct else 'wrong'
                self.outcomes[key] = outcome
                setattr(player, outcome, getattr(player, outcome) + 1)

    def reveal(self):
        final_round = self.settings.single_life and len(self.survivors()) <= 1
        self.enter('reveal', self.settings.continue_seconds or (10 if final_round else None))

    def settle(self):
        self.accepted = len(self.votes) >= 2 and sum(self.votes.values()) * 2 > len(self.votes)
        self.score()
        self.ready.clear()
        if self.ending:
            self.enter('finished')
        else:
            self.reveal()

    async def advance(self):
        expired = self.deadline is not None and clock() >= self.deadline
        if self.phase == 'answer' and (expired or self.playing <= self.answers.keys()):
            self.score()
            self.reveal()
        elif self.phase == 'reveal':
            eligible = self.online() & self.playing
            if expired or (eligible and eligible <= self.ready) or (not eligible and len(self.online()) >= 2):
                await self.next_question()
        elif self.phase == 'draft' and expired:
            self.proposer = None
            self.reveal()
        elif self.phase == 'vote' and (expired or self.playing <= self.votes.keys()):
            self.settle()

    async def act(self, player, body, save):
        action, key = body.action, player.id
        check(body.stage == self.stage, '房间状态已更新，请重试')
        if action in ('start', 'restart', 'settings', 'finish'):
            check(key == self.host, '仅房主可操作', 403)
        if action in ('answer', 'ready', 'draft', 'cancel', 'submit', 'vote'):
            check(key in self.playing and not player.withdrawn, '已淘汰，只能观战' if self.settings.single_life else '从下一题起参赛', 403)
        if action == 'settings':
            check(self.phase == 'lobby' and body.settings, '仅可在开局前设置')
            self.settings = body.settings
        elif action == 'start':
            check(self.phase in ('lobby', 'waiting') and len(self.online()) >= 2, '至少需要两位在线玩家')
            await self.next_question()
        elif action == 'restart':
            check(self.phase == 'finished', '仅可在对战结束后重新开始')
            self.players = {key: member for key, member in self.players.items() if member.online}
            for member in self.players.values():
                member.correct = member.wrong = member.unanswered = 0
                member.withdrawn = False
            self.reset_match()
            if len(self.players) >= 2:
                await self.next_question()
            else:
                self.enter('lobby')
        elif action == 'answer':
            check(self.phase == 'answer' and key not in self.answers, '当前不能作答')
            check('choice' in body.model_fields_set and (body.choice is None or any(
                item['id'] == body.choice for item in self.question['choices'])), '选项无效', 422)
            self.answers[key] = body.choice
        elif action == 'ready':
            check(self.phase == 'reveal', '尚不能进入下一题')
            self.ready.add(key)
        elif action == 'draft':
            check(self.phase == 'reveal' and self.accepted is None, '本题不能再发起反馈')
            self.proposer = key
            self.enter('draft', 90)
        elif action in ('cancel', 'submit'):
            check(self.phase == 'draft' and key == self.proposer, '没有正在填写的反馈')
            if action == 'cancel':
                self.proposer = None
                self.reveal()
            else:
                receipt = await run_in_threadpool(save, self.question, body)
                self.proposal = Proposal.model_validate(dict(receipt))
                self.votes = {key: True}
                self.enter('vote', 30)
        elif action == 'vote':
            check(self.phase == 'vote' and key not in self.votes and body.support is not None, '当前不能投票')
            self.votes[key] = body.support
        elif action == 'finish':
            check(self.phase != 'finished', '对战已经结束')
            self.ending = True
            if self.phase != 'vote':
                if self.phase == 'answer':
                    self.question = None
                self.enter('finished')
        elif action == 'leave':
            player.seen = float('-inf')
            if self.settings.single_life and self.round and self.phase != 'finished':
                player.withdrawn = True
                if len(self.survivors()) <= 1:
                    if self.phase in ('answer', 'waiting'):
                        if self.phase == 'answer':
                            self.question = None
                        self.enter('finished')
                    elif self.phase == 'reveal' and self.deadline is None:
                        self.reveal()
            self.presence()
            if self.phase == 'lobby':
                del self.players[key]
                if not self.players:
                    self.enter('finished')
        self.changed()
        await self.advance()

    def view(self, player):
        question = self.question
        revealed = question is not None and self.phase != 'answer'
        photo = RoomPhoto(**question, box=question['face']['box']) if question else None
        tallies = None
        if revealed:
            voters = {}
            for key, choice in self.answers.items():
                voters.setdefault(choice, []).append(self.players[key].name)
            tallies = [ChoiceTally(choice=choice, count=len(names), nickname=names[0] if len(names) == 1 else None)
                       for choice, names in voters.items()]
        return RoomView(code=self.code, version=self.version, stage=self.stage, phase=self.phase,
                        round=self.round, host=self.host, me=player.id, settings=self.settings, filters=self.filters,
                        remaining=None if self.deadline is None else max(0, self.deadline - clock()),
                        players=[PlayerView(id=item.id, name=item.name, correct=item.correct, wrong=item.wrong,
                                            unanswered=item.unanswered, eliminated=item.eliminated(self.settings.single_life), online=item.online,
                                            playing=item.id in self.playing, answered=item.id in self.answers,
                                            ready=item.id in self.ready) for item in self.players.values()],
                        photo=photo, source_photo=RevealedPhoto(**question) if revealed else None,
                        choice=self.answers.get(player.id), tallies=tallies,
                        answer_name=question['face']['answer_name'] if revealed else None,
                        correct_choice=self.correct if revealed else None, void=self.void, proposer=self.proposer,
                        proposal=self.proposal, accepted=self.accepted, votes_for=sum(self.votes.values()),
                        votes_against=len(self.votes) - sum(self.votes.values()), voted=player.id in self.votes,
                        ending=self.ending, message=self.message)


rooms = {}
polls = 0


def cleanup():
    for code, room in list(rooms.items()):
        if not room.lock.locked() and clock() - room.touched >= 900:
            del rooms[code]


@asynccontextmanager
async def service():
    async def reap():
        while True:
            await asyncio.sleep(60)
            cleanup()
    task = asyncio.create_task(reap())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        rooms.clear()


def router(draw, validate, save_feedback):
    routes = APIRouter(prefix='/api/v1/face-game/rooms')
    def room_for(code):
        room = rooms.get(code.upper())
        check(room and clock() - room.touched < 900, '房间不存在或已失效', 404)
        return room

    def identify(room, token):
        player = next((item for item in room.players.values() if item.token == token), None)
        check(player, '请重新加入房间', 403)
        room.presence(player)
        return player

    def guard(request):
        check(request.headers.get('x-gallery-request') == '1', '缺少请求校验', 403)

    @routes.post('', response_model=Membership, status_code=201)
    async def create_room(body: CreateRoom, request: Request):
        guard(request)
        validate(body.filters)
        cleanup()
        check(len(rooms) < 128, '房间数量已达上限，请稍后重试', 503)
        while True:
            code = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(6))
            if code not in rooms:
                break
        rooms[code] = room = Room(code, body, draw)
        return room.join(body.nickname)

    @routes.post('/{code}/join', response_model=Membership, status_code=201)
    async def join_room(code: str, body: JoinRoom, request: Request):
        guard(request)
        room = room_for(code)
        async with room.lock:
            return room.join(body.nickname)

    @routes.get('/{code}', response_model=RoomView)
    async def read_room(code: str, x_room_token: Annotated[str, Header()], after: int | None = Query(None, ge=0)):
        global polls
        room = room_for(code)
        async with room.lock:
            player = identify(room, x_room_token)
            await room.advance()
            if after != room.version:
                return room.view(player)
            check(polls < 32, '同步繁忙，请稍后重试', 503)
            event = room.event
            delay = min(10, max(0, room.deadline - clock())) if room.deadline is not None else 10
            polls += 1
        try:
            with suppress(TimeoutError):
                await asyncio.wait_for(event.wait(), delay)
        finally:
            polls -= 1
        async with room.lock:
            room.presence()
            await room.advance()
            return room.view(player)

    @routes.post('/{code}/actions', response_model=RoomView)
    async def room_action(code: str, body: RoomAction, request: Request, x_room_token: Annotated[str, Header()]):
        guard(request)
        room = room_for(code)
        async with room.lock:
            player = identify(room, x_room_token)
            await room.advance()
            await room.act(player, body, lambda question, proposal: save_feedback(question, proposal, request))
            return room.view(player)

    return routes
