from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from . import db, game_rooms as games
from .game_boards import Game


class MatchSummary(BaseModel):
    id: str
    code: str
    game: Game
    solo: bool
    phase: games.Phase
    round: int
    members: int
    activity: datetime


class MemberResult(BaseModel):
    name: str
    correct: int
    wrong: int
    unanswered: int
    public_correct: int
    correct_cells: int
    deviation: int
    points: float


class MatchDetail(MatchSummary):
    created_at: datetime | None
    settings: games.RoomSettings
    filters: games.GameFilters
    settled: int
    players: list[MemberResult]


class Matches(BaseModel):
    items: list[MatchSummary]
    total: int


def summary(row, state):
    return dict(id=row['id'], code=row['code'], game=row['game'], solo=row['solo'], phase=row['phase'],
                round=state.round, members=len(state.players), activity=datetime.fromtimestamp(row['touched'], timezone.utc))


def router(admin):
    routes = APIRouter(prefix='/api/v1/admin/game-matches', dependencies=[Depends(admin)])

    @routes.get('', response_model=Matches)
    def matches(game: Game | None = None, mode: Literal['solo', 'multi'] | None = None, phase: games.Phase | Literal['active'] | None = None,
                page: int = Query(1, ge=1, le=1000000), limit: int = Query(20, ge=1, le=100)):
        conditions, args = ['touched>?'], [games.clock() - games.RETENTION]
        for column, value in [('game', game), ('solo', None if mode is None else mode == 'solo')]:
            if value is not None:
                conditions.append(f'{column}=?'); args.append(value)
        if phase == 'active':
            conditions.append("phase NOT IN ('lobby', 'finished')")
        elif phase is not None:
            conditions.append('phase=?'); args.append(phase)
        source = ' FROM game_matches WHERE ' + ' AND '.join(conditions)
        with db.connect() as conn:
            conn.execute('BEGIN')
            total = conn.execute('SELECT count(*)' + source, args).fetchone()[0]
            rows = conn.execute('SELECT *' + source + ' ORDER BY touched DESC,rowid DESC LIMIT ? OFFSET ?', [*args, limit, (page - 1) * limit])
            return Matches(total=total, items=[MatchSummary(**summary(row, games.MatchState.model_validate_json(row['state']))) for row in rows])

    @routes.get('/{match_id}', response_model=MatchDetail)
    def match(match_id: str):
        with db.connect() as conn:
            row = conn.execute('SELECT * FROM game_matches WHERE id=? AND touched>?', (match_id, games.clock() - games.RETENTION)).fetchone()
        games.check(row, '对局不存在或已失效', 404)
        state = games.MatchState.model_validate_json(row['state'])
        return MatchDetail(**summary(row, state), created_at=state.created_at, settings=state.settings, filters=state.filters, settled=state.settled,
            players=[MemberResult(**vars(member), points=float(state.scores.get(member.id, 0))) for member in state.players.values()])

    return routes
