import { expect, it } from 'vitest';
import { answer, faceZoom, feedbackReceipt, game, openRound, score, type Question } from '../src/face-game';

it('zooms a small face beyond 2x and keeps centered and edge crops inside the photo', () => {
  expect(faceZoom([280, 80, 40, 40], 800, 400)).toEqual({ scale: 5, left: -1.375, top: -.75 });
  expect(faceZoom([760, 360, 40, 40], 800, 400)).toEqual({ scale: 5, left: -4, top: -4 });
});

it('limits zoom by either face dimension without shrinking large faces', () => {
  expect(faceZoom([0, 0, 320, 40], 800, 400).scale).toBe(1.25);
  expect(faceZoom([0, 0, 40, 160], 800, 400).scale).toBe(1.25);
  expect(faceZoom([0, 0, 40, 220], 800, 400)).toEqual({ scale: 1, left: 0, top: 0 });
});

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
