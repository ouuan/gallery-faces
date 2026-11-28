import asyncio
import random
import secrets
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator
from starlette.concurrency import run_in_threadpool

from . import db


Nickname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
Phase = Literal['lobby', 'loading', 'answer', 'reveal', 'draft', 'vote', 'waiting', 'finished']
clock = time.time
RETENTION = 24 * 3600


class RoomSettings(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    round_limit: int = Field(default=25, ge=0, le=999)
    answer_seconds: int = Field(default=15, ge=3, le=300)
    continue_seconds: int = Field(default=10, ge=0, le=300)
    cropped: bool = True
    single_life: bool = False
    allow_late_join: bool = True
    grid: bool = True
    grid_size: int = Field(default=10, ge=2, le=16)
    grid_cells: int = Field(default_factory=lambda data: data['grid_size'] ** 2, ge=1, le=256)
    grid_seconds: float = Field(default=0.2, ge=0.1, le=60)

    @field_validator('grid_cells')
    @classmethod
    def validate_grid_cells(cls, value: int, info: ValidationInfo) -> int:
        if 'grid_size' in info.data and value > info.data['grid_size'] ** 2:
            raise ValueError('显示格数不能超过网格总数')
        return value

class GameFilters(BaseModel):
    people: str = ''
    publishers: str = ''
    match: Literal['any', 'all', 'exact', 'subset'] = 'any'
    start: str = ''
    end: str = ''
    include_no_faces: bool = False


class JoinRoom(BaseModel):
    nickname: Nickname


class RoomPreview(BaseModel):
    phase: Phase
    members: int
    settings: RoomSettings
    filters: GameFilters


class CreateRoom(BaseModel):
    nickname: Annotated[str, StringConstraints(strip_whitespace=True, max_length=24)] = ''
    solo: bool = False
    settings: RoomSettings = Field(default_factory=RoomSettings)
    filters: GameFilters = Field(default_factory=GameFilters)


class Membership(BaseModel):
    code: str
    token: str


class RoomAction(BaseModel):
    action: Literal['settings', 'start', 'restart', 'image_loaded', 'answer', 'give_up', 'ready', 'draft', 'cancel', 'submit', 'vote', 'dispute', 'finish', 'leave']
    stage: int
    match_id: str
    settings: RoomSettings | None = None
    filters: GameFilters | None = None
    choice: int | None = None
    guess_date: date | None = None
    support: bool | None = None
    suggested_person_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    not_face: bool = False
    content: str = Field(default='', max_length=1000)
    feedback_id: int | None = Field(default=None, gt=0, le=9223372036854775807)


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
    correct_cells: int = 0
    unanswered: int
    eliminated: bool
    online: bool
    playing: bool
    answered: bool
    ready: bool
    public_correct: int = 0
    eligible: bool = False
    disputed: int = 0
    early: int = 0
    late: int = 0


class Proposal(BaseModel):
    suggested_name: str | None
    suggested_person_id: int | None
    not_face: bool
    content: str


class RevealedPhoto(BaseModel):
    group_id: int
    image_id: int


class HistoryPhoto(BaseModel):
    image_url: str
    width: int
    height: int
    first_date: date
    last_date: date


class HistoryStatus(BaseModel):
    photo: HistoryPhoto | None
    my_guess: date | None
    correct_date: date | None
    guesses: dict[int, date] | None
    settled: int
    scores: dict[int, float]
    closest: list[int] | None
    total_deviations: dict[int, int]


class ChoiceTally(BaseModel):
    choice: int | None
    count: int
    nickname: str | None


class GridView(BaseModel):
    order: list[int]
    elapsed: float
    wrong_choices: list[int | None]
    correct_cells: int | None = None
    gave_up: bool = False


class RoomView(BaseModel):
    match_id: str
    solo: bool
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
    revealed_face_id: int | None = None
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
    history: HistoryStatus | None = None
    grid: GridView | None = None


@dataclass
class Player:
    id: int
    name: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    seen: float = field(default_factory=lambda: clock())
    online: bool = True
    correct: int = 0
    wrong: int = 0
    correct_cells: int = 0
    unanswered: int = 0
    deviation: int = 0
    withdrawn: bool = False
    eligible: bool = True
    public_correct: int = 0
    public_stopped: bool = False
    disputed: int = 0
    early: int = 0
    late: int = 0

    def eliminated(self, single_life):
        return single_life and (self.withdrawn or self.wrong + self.unanswered > 0)


def check(condition, message, status=409):
    if not condition:
        raise HTTPException(status, message)


@dataclass
class GridRound:
    order: list[int]
    started: float
    attempts: list[tuple[int, int | None, int]] = field(default_factory=list)
    credited: list[tuple[int, int, int, int]] = field(default_factory=list)
    passed: set[int] = field(default_factory=set)
    ended_by_pass: bool = False

    def visible_cells(self, interval):
        return min(len(self.order), int((clock() - self.started) / interval))

    def submit(self, key, choice, interval):
        check(key not in self.passed, '本题已放弃作答')
        check(not any(player == key and tried == choice for player, tried, _ in self.attempts), '你已选过这一项')
        cells = self.visible_cells(interval)
        check(cells > 0, '首格揭示后才能作答')
        self.attempts.append((key, choice, cells))

    def settle(self, players, correct, valid):
        for key, right, wrong, cells in self.credited:
            players[key].correct -= right
            players[key].wrong -= wrong
            players[key].correct_cells -= cells
        self.credited.clear()
        if not valid or (not self.ended_by_pass and not any(choice == correct for _, choice, _ in self.attempts)):
            return False
        for key, choice, cells in self.attempts:
            right = choice == correct
            self.credited.append((key, int(right), int(not right), cells if right else 0))
            if right:
                players[key].correct += 1
                players[key].correct_cells += cells
                break
            players[key].wrong += 1
        return True


class Room:
    game = 'face-game'

    def __init__(self, code, setup, draw, validate):
        self.code, self.settings, self.filters, self.draw = code, setup.settings, setup.filters, draw
        self.solo = setup.solo
        if self.game == 'face-game' and self.settings.single_life:
            self.settings.round_limit = 0
        self.validate_filters = validate
        self.players = {}
        self.host = self.serial = self.version = self.stage = 0
        self.phase = 'lobby'
        self.lock, self.event = asyncio.Lock(), asyncio.Event()
        self.reset_match()

    def reset_match(self):
        self.match_id = secrets.token_hex(16)
        self.touched = clock()
        self.created_at = datetime.fromtimestamp(self.touched, timezone.utc)
        self.loaded = set()
        self.public_round = 0
        self.natural = False
        self.grid = None
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
        check(not self.solo or not self.players, '单人对局不能加入')
        check(self.phase != 'finished' and not self.ending, '对战已经结束')
        check(not self.settings.single_life or not self.round, '一命模式开局后不能加入')
        check(self.settings.allow_late_join or not self.round, '本房间不允许中途加入')
        check(len(self.players) < 12, '房间已满')
        check(all(player.name != name for player in self.players.values()), '房间内已有相同昵称')
        self.serial += 1
        player = self.new_player(name)
        player.eligible = self.round == 0
        self.players[player.id] = player
        if self.phase in ('loading', 'answer'):
            self.playing.add(player.id)
        if not self.host:
            self.host = player.id
        self.touched = clock()
        self.changed()
        return Membership(code=self.code, token=player.token)

    def new_player(self, name):
        return Player(self.serial, name)

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
        if self.round > self.public_round:
            self.public_round = self.round
            if self.game == 'face-game':
                for key, player in self.players.items():
                    if player.public_stopped:
                        continue
                    right = not self.accepted and not self.void and key in self.answers and self.answers[key] == self.correct
                    player.public_correct += int(right)
                    if self.settings.single_life and not right:
                        player.public_stopped = True
        participants = self.survivors() if self.settings.single_life else self.online()
        if (self.settings.round_limit and self.round >= self.settings.round_limit) or (
                self.settings.single_life and self.round and len(participants) < self.minimum):
            self.natural = True
            self.enter('finished')
            return
        if len(participants) < self.minimum:
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
        for key, player in self.players.items():
            if key not in participants and not player.eliminated(self.settings.single_life):
                player.eligible = False
        self.playing, self.answers, self.ready, self.outcomes = participants, {}, set(), {}
        self.proposer = self.proposal = self.accepted = None
        self.votes, self.void = {}, False
        self.loaded = set()
        self.enter('loading', 5)
        if self.settings.grid:
            count = self.settings.grid_size ** 2
            self.grid = GridRound(random.sample(range(count), self.settings.grid_cells), self.deadline)

    @property
    def minimum(self):
        return 1 if self.solo else 2

    def score(self):
        person = self.question['face']['person_id']
        if self.accepted:
            person = self.proposal.suggested_person_id
        self.void = person is None
        self.correct = next((item['id'] for item in self.question['choices'] if item['id'] == person), None)
        if self.grid:
            self.void = not self.grid.settle(self.players, self.correct, not self.void)
            return
        for key in self.playing:
            player = self.players[key]
            previous = self.outcomes.pop(key, None)
            if previous:
                setattr(player, previous, getattr(player, previous) - 1)
            if not self.void:
                outcome = 'unanswered' if key not in self.answers else 'correct' if self.answers[key] == self.correct else 'wrong'
                self.outcomes[key] = outcome
                setattr(player, outcome, getattr(player, outcome) + 1)

    def answer(self, body):
        check('choice' in body.model_fields_set and (body.choice is None or any(
            item['id'] == body.choice for item in self.question['choices'])), '选项无效', 422)
        return body.choice

    def reveal(self):
        final_round = self.settings.single_life and len(self.survivors()) < self.minimum
        self.enter('reveal', None if self.solo else self.settings.continue_seconds or (10 if final_round else None))

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
        if self.phase == 'loading':
            if expired or (self.online() & self.playing) <= self.loaded:
                started = min(clock(), self.deadline)
                if self.grid:
                    self.grid.started = started
                self.enter('answer')
                self.deadline = started + self.settings.answer_seconds + (len(self.grid.order) * self.settings.grid_seconds if self.grid else 0)
                expired = clock() >= self.deadline
        if self.phase == 'answer':
            if self.grid:
                eligible = self.online() & self.playing
                if not expired and (not eligible or not eligible <= self.grid.passed):
                    return
                self.grid.ended_by_pass = True
                if self.solo and not self.grid.attempts:
                    self.players[self.host].unanswered += 1
            elif not expired and not self.playing <= self.answers.keys():
                return
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
        if body.match_id != self.match_id:
            if action in ('image_loaded', 'ready'):
                return
            raise HTTPException(409, '原对局已结束，本次操作未计入')
        if body.stage != self.stage and action not in ('finish', 'leave'):
            if action in ('image_loaded', 'ready'):
                return
            if action == 'answer':
                if self.grid and self.phase == 'reveal' and body.stage + 1 == self.stage:
                    winner = next((member for member, right, _, _ in self.grid.credited if right), None)
                    if winner is not None:
                        raise HTTPException(409, f'{self.players[winner].name}已抢先答对')
                raise HTTPException(409, '答题时间已到，本次答案未计入')
            if action == 'vote':
                raise HTTPException(409, '投票已结束，本次投票未计入')
            raise HTTPException(409, '房间状态已更新，请确认当前题目')
        if action in ('start', 'restart', 'settings', 'finish'):
            check(key == self.host, '仅房主可操作', 403)
        if action in ('image_loaded', 'answer', 'give_up', 'ready', 'draft', 'cancel', 'submit', 'vote'):
            check(key in self.playing and not player.withdrawn, '已淘汰，只能观战' if self.settings.single_life else '从下一题起参赛', 403)
        if action == 'settings':
            check(self.phase == 'lobby' and (body.settings or body.filters), '仅可在开局前设置')
            if body.filters is not None:
                self.validate_filters(body.filters)
                self.filters = body.filters
            if body.settings is not None:
                self.settings = body.settings
                if self.settings.single_life:
                    self.settings.round_limit = 0
        elif action == 'start':
            check(self.phase in ('lobby', 'waiting') and len(self.online()) >= self.minimum, '在线人数不足')
            await self.next_question()
        elif action == 'restart':
            check(self.phase == 'finished', '仅可在对战结束后重新开始')
            self.players = {key: member for key, member in self.players.items() if member.online}
            for member in self.players.values():
                member.correct = member.wrong = member.correct_cells = member.unanswered = member.deviation = 0
                member.withdrawn = False
                member.eligible = True
                member.public_correct = 0
                member.public_stopped = False
                member.disputed = member.early = member.late = 0
            self.reset_match()
            if len(self.players) >= self.minimum:
                await self.next_question()
            else:
                self.enter('lobby')
        elif action == 'image_loaded':
            check(self.phase == 'loading', '当前不在加载照片')
            self.loaded.add(key)
            await self.advance()
            return
        elif action == 'answer':
            check(self.phase == 'answer' and key not in self.answers, '当前不能作答')
            choice = self.answer(body)
            if self.grid:
                self.grid.submit(key, choice, self.settings.grid_seconds)
                if self.solo:
                    self.grid.ended_by_pass = True
                person = self.question['face']['person_id']
                correct = next((item['id'] for item in self.question['choices'] if item['id'] == person), None)
                if not self.solo and choice != correct:
                    if self.settings.single_life:
                        self.grid.passed.add(key)
                        self.changed()
                        await self.advance()
                    return
                self.answers[key] = choice
                self.score()
                self.reveal()
            else:
                self.answers[key] = choice
        elif action == 'give_up':
            check(self.phase == 'answer' and self.grid, '当前不能放弃作答')
            check(self.grid.visible_cells(self.settings.grid_seconds) == len(self.grid.order), '达到显示格数后才能放弃作答')
            check(key not in self.grid.passed, '本题已放弃作答')
            self.grid.passed.add(key)
        elif action == 'ready':
            check(self.phase == 'reveal', '尚不能进入下一题')
            self.ready.add(key)
        elif action == 'dispute':
            check(self.solo and self.game == 'face-game' and self.phase == 'reveal' and self.accepted is None
                  and key in self.answers and self.answers[key] != self.correct, '本题不能标记存疑')
            face = self.question['face']
            with db.connect() as conn:
                receipt = conn.execute('SELECT 1 FROM feedback WHERE id=? AND image_id=? AND face_id=? AND face_revision=?',
                    (body.feedback_id, self.question['image_id'], face['id'], face['revision'])).fetchone()
            check(receipt, '本次反馈不属于题目人脸')
            self.accepted = False
            player.disputed += 1
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
                if self.solo:
                    self.accepted = False
                    if key in self.answers and self.answers[key] != self.correct:
                        player.disputed += 1
                    self.reveal()
                else:
                    self.votes = {key: True}
                    self.enter('vote', 30)
        elif action == 'vote':
            check(self.phase == 'vote' and key not in self.votes and body.support is not None, '当前不能投票')
            self.votes[key] = body.support
        elif action == 'finish':
            check(self.phase != 'finished', '对战已经结束')
            self.ending = True
            if self.phase != 'vote':
                if self.phase in ('loading', 'answer'):
                    self.question = None
                self.enter('finished')
        elif action == 'leave':
            if self.phase != 'finished':
                player.eligible = False
            player.seen = clock() - RETENTION
            if self.settings.single_life and self.round and self.phase != 'finished':
                player.withdrawn = True
                if len(self.survivors()) <= 1:
                    if self.phase in ('loading', 'answer', 'waiting'):
                        if self.phase in ('loading', 'answer'):
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

    def question_view(self, player, question, revealed):
        photo = RoomPhoto(**question, box=question['face']['box']) if question else None
        tallies = None
        if revealed:
            voters = {}
            attempts = ((key, choice) for key, choice, _ in self.grid.attempts) if self.grid else self.answers.items()
            for key, choice in attempts:
                voters.setdefault(choice, []).append(self.players[key].name)
            tallies = [ChoiceTally(choice=choice, count=len(names), nickname=names[0] if len(names) == 1 else None)
                       for choice, names in voters.items()]
        return dict(photo=photo, choice=self.answers.get(player.id), tallies=tallies,
                    answer_name=question['face']['answer_name'] if revealed else None)

    def view(self, player):
        question = self.question
        revealed = question is not None and self.phase not in ('loading', 'answer')
        grid = None
        if self.grid and question:
            grid = GridView(order=self.grid.order, elapsed=max(0, clock() - self.grid.started),
                            gave_up=player.id in self.grid.passed,
                            correct_cells=(self.grid.attempts[0][2] if self.solo and self.grid.attempts and revealed else
                                           next((cells for _, right, _, cells in self.grid.credited if right), None)), wrong_choices=[
                choice for key, choice, _ in self.grid.attempts if key == player.id and (not revealed or choice != self.correct)])
        return RoomView(match_id=self.match_id, solo=self.solo, code=self.code, version=self.version, stage=self.stage, phase=self.phase,
                        round=self.round, host=self.host, me=player.id, settings=self.settings, filters=self.filters,
                        remaining=None if self.deadline is None else max(0, self.deadline - clock()),
                        grid=grid, players=[PlayerView(id=item.id, name=item.name, correct=item.correct, correct_cells=item.correct_cells,
                                            wrong=item.wrong + (len(grid.wrong_choices) if grid and not revealed and item == player else 0),
                                            unanswered=item.unanswered, eliminated=item.eliminated(self.settings.single_life), online=item.online,
                                            playing=item.id in self.playing, answered=item.id in self.answers,
                                            ready=item.id in self.ready, public_correct=item.public_correct, disputed=item.disputed,
                                            early=item.early, late=item.late,
                                            eligible=self.can_upload(item)) for item in self.players.values()],
                        **self.question_view(player, question, revealed),
                        source_photo=RevealedPhoto(**question) if revealed else None,
                        revealed_face_id=question['face']['id'] if revealed and self.solo and self.game == 'face-game' else None,
                        correct_choice=self.correct if revealed else None, void=self.void, proposer=self.proposer,
                        proposal=self.proposal, accepted=self.accepted, votes_for=sum(self.votes.values()),
                        votes_against=len(self.votes) - sum(self.votes.values()), voted=player.id in self.votes,
                        ending=self.ending, message=self.message)

    def can_upload(self, player):
        return bool(self.phase == 'finished' and self.natural and player.eligible and self.round and
                    (self.settings.round_limit or self.settings.single_life) and (self.solo or not self.settings.grid))


class HistoryRoom(Room):
    game = 'history-quiz'

    def __init__(self, code, setup, draw, validate):
        super().__init__(code, setup, draw, validate)
        self.settings.grid = self.settings.cropped = self.settings.single_life = False

    def reset_match(self):
        super().reset_match()
        self.settled = self.midpoint_total = 0
        self.scores = {}
        self.closest = []

    def new_player(self, name):
        return Player(self.serial, name, unanswered=self.settled, deviation=self.midpoint_total)

    def answer(self, body):
        guess = body.guess_date
        check(guess is not None and self.question['first_date'] <= guess <= self.question['last_date'], '请选择范围内的日期', 422)
        return guess

    async def act(self, player, body, save):
        check(body.action not in ('draft', 'cancel', 'submit', 'vote'), '史官测验不支持纠错投票')
        if body.action == 'settings' and body.settings:
            body.settings.grid = body.settings.cropped = body.settings.single_life = False
        await super().act(player, body, save)

    def score(self):
        first, last, correct = (self.question[key] for key in ('first_date', 'last_date', 'correct_date'))
        midpoint = first + timedelta(days=(last - first).days // 2)
        deviations = {key: abs((guess - correct).days) for key, guess in self.answers.items()}
        best = min(deviations.values(), default=None)
        self.closest = [key for key, days in deviations.items() if days == best]
        for key in self.closest:
            self.scores[key] = self.scores.get(key, 0) + Fraction(1, len(self.closest))
        self.settled += 1
        midpoint_deviation = abs((midpoint - correct).days)
        self.midpoint_total += midpoint_deviation
        for key, player in self.players.items():
            player.deviation += deviations.get(key, midpoint_deviation)
            if key in self.answers:
                player.early += int(self.answers[key] < correct)
                player.late += int(self.answers[key] > correct)
            if key not in self.answers:
                player.unanswered += 1

    def question_view(self, player, question, revealed):
        history = HistoryStatus(photo=HistoryPhoto(**question) if question else None,
                                my_guess=self.answers.get(player.id), guesses=self.answers if revealed else None,
                                correct_date=question['correct_date'] if revealed else None, settled=self.settled,
                                scores={key: float(self.scores.get(key, 0)) for key in self.players},
                                closest=self.closest if revealed else None,
                                total_deviations={key: member.deviation for key, member in self.players.items()})
        return dict(photo=None, choice=None, tallies=None, answer_name=None, history=history)


rooms = {}
polls = 0


class MatchState(BaseModel):
    created_at: datetime | None = None
    natural: bool
    public_round: int
    settings: RoomSettings
    filters: GameFilters
    players: dict[int, Player]
    host: int
    serial: int
    version: int
    stage: int
    round: int
    question: dict | None
    deadline: float | None
    correct: int | None
    proposer: int | None
    proposal: Proposal | None
    accepted: bool | None
    ending: bool
    void: bool
    message: str
    loaded: set[int]
    playing: set[int]
    ready: set[int]
    outcomes: dict[int, str]
    answers: dict[int, int | date | None]
    votes: dict[int, bool]
    grid: GridRound | None
    settled: int = 0
    midpoint_total: int = 0
    scores: dict[int, Fraction] = Field(default_factory=dict)
    closest: list[int] = Field(default_factory=list)


def persist(room):
    state = MatchState.model_validate(room, from_attributes=True).model_dump_json()
    with db.connect() as conn:
        conn.execute('INSERT INTO game_matches VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                     'phase=excluded.phase,touched=excluded.touched,state=excluded.state',
                     (room.match_id, room.code, room.game, room.solo, room.phase, room.touched, state))


def restore(code, room_type, draw, validate):
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM game_matches WHERE code=? AND game=? AND touched>? ORDER BY rowid DESC LIMIT 1',
                           (code, room_type.game, clock() - RETENTION)).fetchone()
    if not row:
        return None
    state = MatchState.model_validate_json(row['state'])
    setup = CreateRoom(nickname='恢复', settings=state.settings, filters=state.filters, solo=bool(row['solo']))
    room = room_type(code, setup, draw, validate)
    for key, value in state:
        setattr(room, key, value)
    if room.game == 'history-quiz' and room.question:
        for key in ('first_date', 'last_date', 'correct_date'):
            room.question[key] = date.fromisoformat(room.question[key])
    room.match_id, room.phase, room.touched = row['id'], row['phase'], row['touched']
    return room


def cleanup():
    with db.connect() as conn:
        conn.execute('DELETE FROM game_matches WHERE touched<=?', (clock() - RETENTION,))
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


def router(draw, validate, save_feedback=None, *, room_type=Room):
    routes = APIRouter(prefix=f'/api/v1/{room_type.game}/rooms')
    def room_for(code):
        code = code.upper()
        room = rooms.get(code)
        if not room:
            room = restore(code, room_type, draw, validate)
            if room:
                rooms[code] = room
        check(room and room.game == room_type.game and clock() - room.touched < RETENTION, '房间不存在或已失效', 404)
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
        check(body.solo or body.nickname, '请填写昵称', 422)
        validate(body.filters)
        cleanup()
        check(sum(room.phase != 'finished' and clock() - room.touched < 900 for room in rooms.values()) < 128,
              '活跃对局数量已达上限，请稍后重试', 503)
        while True:
            code = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(6))
            with db.connect() as conn:
                if code not in rooms and not conn.execute('SELECT 1 FROM game_matches WHERE code=?', (code,)).fetchone():
                    break
        rooms[code] = room = room_type(code, body, draw, validate)
        member = room.join(body.nickname)
        if room.solo:
            await room.next_question()
        persist(room)
        return member

    @routes.post('/{code}/join', response_model=Membership, status_code=201)
    async def join_room(code: str, body: JoinRoom, request: Request):
        guard(request)
        room = room_for(code)
        async with room.lock:
            await room.advance()
            member = room.join(body.nickname)
            persist(room)
            return member

    @routes.get('/{code}/preview', response_model=RoomPreview)
    async def preview_room(code: str):
        room = room_for(code)
        return RoomPreview(phase=room.phase, members=len(room.players), settings=room.settings, filters=room.filters)

    @routes.get('/{code}', response_model=RoomView)
    async def read_room(code: str, x_room_token: Annotated[str, Header()], after: int | None = Query(None, ge=0)):
        global polls
        room = room_for(code)
        async with room.lock:
            player = identify(room, x_room_token)
            await room.advance()
            persist(room)
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
            persist(room)
            return room.view(player)

    @routes.post('/{code}/actions', response_model=RoomView)
    async def room_action(code: str, body: RoomAction, request: Request, x_room_token: Annotated[str, Header()]):
        guard(request)
        room = room_for(code)
        async with room.lock:
            player = identify(room, x_room_token)
            await room.advance()
            try:
                await room.act(player, body, lambda question, proposal: save_feedback(question, proposal, request))
            finally:
                persist(room)
            return room.view(player)

    return routes
