(() => {
  'use strict';

  const app = window.WorldFeed;
  const photos = window.WorldFeedPhotoMap || {};
  if (!app?.story?.stories) return;

  const storyPhotoRole = {
    maker: 'maker-studio',
    'market-studio': 'market-studio',
    harbor: 'hero-harbor',
    cinema: 'small-cinema'
  };

  Object.entries(storyPhotoRole).forEach(([storyId, role]) => {
    const story = app.story.stories[storyId];
    const photo = photos[role];
    if (!story || !photo) return;
    story.image = photo.src;
    story.alt = `${photo.alt} · 이야기 내용과 분리된 대표 실사 이미지`;
  });

  const caption = document.querySelector('[data-story-caption]');
  if (caption) {
    const normalizeCaption = () => {
      const story = app.story.stories[document.querySelector('.review-shell')?.dataset.storyId] || app.story.stories.maker;
      const expected = `${story.title.join(' ')} · 대표 실사 이미지는 분위기 참고용이며 본문과 출처 정보는 UX 검토용 합성입니다.`;
      if (caption.textContent !== expected) caption.textContent = expected;
    };
    new MutationObserver(normalizeCaption).observe(caption, { childList: true, characterData: true, subtree: true });
    queueMicrotask(normalizeCaption);
  }

  document.documentElement.dataset.worldFeedWorkspace = 'v4';
})();
