import hashlib
import json
import secrets
from datetime import datetime, timezone
from fractions import Fraction
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from . import db, game_rooms as games


Game = Literal['face-game', 'history-quiz']


class BoardRules(BaseModel):
    settings: games.RoomSettings = Field(default_factory=games.RoomSettings)
    filters: games.GameFilters = Field(default_factory=games.GameFilters)


class Board(BaseModel):
    settings: games.RoomSettings
    filters: games.GameFilters
    id: str
    game: Game
    members: int = 0


class Upload(BaseModel):
    nickname: games.Nickname | None = None


class Record(BaseModel):
    nickname: str
    correct: int
    cells: int
    deviation: int
    rounds: int
    recorded_at: datetime


class RankedRecord(Record):
    rank: int


class BoardView(BaseModel):
    board: Board
    records: list[RankedRecord]


def board_for(game, rules, parse, bounds):
    ids, accounts = parse(rules.filters.people, rules.filters.publishers)
    start, end = bounds(rules.filters.start, rules.filters.end)
    filters = rules.filters.model_copy(update=dict(people=','.join(map(str, ids)),
        publishers=','.join(sorted({f'{platform}:{author.lower()}' for platform, author in accounts})), start=start or '', end=end or ''))
    source = rules.settings
    face = game == 'face-game'
    life = face and source.single_life
    grid = face and source.grid
    rules_key = dict(round_limit=0 if life else source.round_limit, answer_seconds=source.answer_seconds)
    if face:
        rules_key.update(single_life=life, cropped=source.cropped, grid=grid)
    if grid:
        rules_key.update(grid_size=source.grid_size, grid_seconds=source.grid_seconds)
    settings = games.RoomSettings(**(dict(cropped=False, grid=False) | rules_key))
    key = json.dumps([game, rules_key, filters.model_dump()], sort_keys=True).encode()
    return Board(id=hashlib.sha256(key).hexdigest(), game=game, settings=settings, filters=filters)


def rank_key(board, record):
    if board.game == 'history-quiz':
        return (Fraction(record.deviation, record.rounds),)
    return (-record.correct, Fraction(record.cells, record.correct) if board.settings.grid and record.correct else 0)


def router(parse, bounds):
    routes = APIRouter(prefix='/api/v1/{game}')

    @routes.post('/boards/current', response_model=BoardView)
    def current(game: Game, rules: BoardRules):
        board = board_for(game, rules, parse, bounds)
        with db.connect() as conn:
            rows = conn.execute('SELECT * FROM game_records WHERE board=? ORDER BY nickname', (board.id,))
            ordered = sorted((Record(**row) for row in rows), key=lambda record: rank_key(board, record))
        records = []
        previous, rank = None, 0
        for index, record in enumerate(ordered, 1):
            key = rank_key(board, record)
            if key != previous:
                previous, rank = key, index
            records.append(RankedRecord(**record.model_dump(), rank=rank))
        board.members = len(records)
        return BoardView(board=board, records=records)

    @routes.post('/boards/list', response_model=list[Board])
    def boards(game: Game, rules: BoardRules, scope: Literal['filters', 'all'] = 'filters'):
        board = board_for(game, rules, parse, bounds)
        with db.connect() as conn:
            rows = conn.execute('SELECT b.*,count(*) AS members FROM game_boards b JOIN game_records r ON b.id=r.board '
                'WHERE b.game=? AND (? OR b.filters=?) GROUP BY b.id ORDER BY members DESC,b.id',
                (game, scope == 'all', board.filters.model_dump_json()))
            return [Board(id=row['id'], game=game, settings=json.loads(row['settings']), filters=json.loads(row['filters']), members=row['members']) for row in rows]

    @routes.post('/matches/{match_id}/score', response_model=Record)
    def upload(game: Game, match_id: str, body: Upload, request: Request, x_room_token: Annotated[str, Header()]):
        games.check(request.headers.get('x-gallery-request') == '1', '缺少请求校验', 403)
        with db.connect(True) as conn:
            row = conn.execute('SELECT * FROM game_matches WHERE id=? AND game=? AND touched>?',
                               (match_id, game, games.clock() - games.RETENTION)).fetchone()
            games.check(row, '对局不存在或已失效', 404)
            state = games.MatchState.model_validate_json(row['state'])
            player = next((member for member in state.players.values() if secrets.compare_digest(member.token.encode(), x_room_token.encode())), None)
            games.check(player, '没有此对局的参赛凭据', 403)
            games.check(row['phase'] == 'finished' and state.natural and player.eligible and state.round and
                        (state.settings.single_life or state.settings.round_limit) and (row['solo'] or not state.settings.grid), '本局成绩不能上传')
            nickname = body.nickname if row['solo'] else player.name
            games.check(nickname and (row['solo'] or body.nickname in (None, nickname)), '请使用自己的昵称', 422)
            board = board_for(game, state, parse, bounds)
            prior = conn.execute('SELECT nickname FROM game_uploads WHERE match_id=? AND player=?', (match_id, player.id)).fetchone()
            games.check(not prior or prior[0] == nickname, '本局成绩已经使用其他昵称上传')
            conn.execute('INSERT OR IGNORE INTO game_boards VALUES(?,?,?,?)',
                         (board.id, game, board.settings.model_dump_json(), board.filters.model_dump_json()))
            best = conn.execute('SELECT * FROM game_records WHERE board=? AND nickname=?', (board.id, nickname)).fetchone()
            result = Record(nickname=nickname, correct=player.public_correct, cells=player.correct_cells, deviation=player.deviation,
                            rounds=state.round, recorded_at=datetime.now(timezone.utc))
            if best and (prior or rank_key(board, Record(**best)) <= rank_key(board, result)):
                result = Record(**best)
            else:
                conn.execute('INSERT OR REPLACE INTO game_records VALUES(?,?,?,?,?,?,?)',
                    (board.id, nickname, result.correct, result.cells, result.deviation, result.rounds, result.recorded_at.isoformat()))
            conn.execute('INSERT OR IGNORE INTO game_uploads VALUES(?,?,?)', (match_id, player.id, nickname))
            return result

    return routes
