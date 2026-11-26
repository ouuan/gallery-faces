import { expect, it } from 'vitest';
import { answer, feedbackReceipt, game, openRound, score, type Question } from '../src/face-game';

it('counts a delayed receipt against only its original wrong round', () => {
  const question: Question = { group_id: 1, image_id: 2, width: 100, height: 100, image_url: '/picture', choices: [{ id: 3, name: '甲' }],
    face: { id: 5, person_id: 3, box: [5, 5, 30, 30], revision: 0, locked: false } };
  game.outcomes = [];
  expect(score([]).accuracy).toBe('—');
  openRound(question); answer(3);
  openRound(question); answer(null); answer(3);
  const received = feedbackReceipt(game.round!, game.outcomes);
  openRound(question); answer(3);
  received(null); received(100);
  expect(score(game.outcomes)).toEqual({ correct: 2, wrong: 1, disputed: 0, accuracy: '67%', streak: 1 });
  received(5); received(5);
  feedbackReceipt(game.round!, game.outcomes)(5);
  expect(score(game.outcomes)).toEqual({ correct: 2, wrong: 0, disputed: 1, accuracy: '100%', streak: 2 });
});
