(() => {
  'use strict';

  const photos = {
    'hero-harbor': {
      src: 'https://images.unsplash.com/photo-1636649148027-5a18656382e7?auto=format&fit=crop&w=2200&q=82',
      alt: '비에 젖은 야간 도심과 보행자의 불빛',
      position: 'center 58%'
    },
    'neighborhood-bookshop': {
      src: 'https://images.unsplash.com/photo-1646812965105-87821655690f?auto=format&fit=crop&w=1800&q=82',
      alt: '한 사람이 걷는 조용한 야간 골목과 가로등',
      position: 'center 54%'
    },
    'night-market': {
      src: 'https://images.unsplash.com/photo-1648973174435-fc50d62a6198?auto=format&fit=crop&w=1800&q=82',
      alt: '사람들이 오가는 야간 시장의 조명과 가게',
      position: 'center 54%'
    },
    'sea-train': {
      src: 'https://images.unsplash.com/photo-1534726972605-17962f8743d2?auto=format&fit=crop&w=1900&q=82',
      alt: '밤거리의 사람들과 도시 간판 불빛',
      position: 'center 46%'
    },
    'maker-studio': {
      src: 'https://images.unsplash.com/photo-1646812965105-87821655690f?auto=format&fit=crop&w=2000&q=82',
      alt: '늦은 저녁 골목 안쪽으로 이어지는 작업 공간의 분위기',
      position: 'center 48%'
    },
    'stadium-culture': {
      src: 'https://images.unsplash.com/photo-1534726972605-17962f8743d2?auto=format&fit=crop&w=1800&q=82',
      alt: '사람들이 모여 있는 야간 도시 거리의 에너지',
      position: 'center 52%'
    },
    'small-cinema': {
      src: 'https://images.unsplash.com/photo-1768511813767-df4ade9ddca7?auto=format&fit=crop&w=2000&q=82',
      alt: '붉은 간판 아래 사람들이 걷는 야간 문화 거리',
      position: 'center 46%'
    },
    'market-studio': {
      src: 'https://images.unsplash.com/photo-1648973174435-fc50d62a6198?auto=format&fit=crop&w=2000&q=82',
      alt: '야간 시장 안쪽의 작은 가게와 사람들',
      position: 'center 56%'
    },
    'story-harbor': {
      src: 'https://images.unsplash.com/photo-1636649148027-5a18656382e7?auto=format&fit=crop&w=2200&q=82',
      alt: '젖은 도심의 야간 산책 장면',
      position: 'center 58%'
    },
    'why-harbor': {
      src: 'https://images.unsplash.com/photo-1534726972605-17962f8743d2?auto=format&fit=crop&w=1800&q=82',
      alt: '야간 도시 골목의 사람과 불빛',
      position: 'center 48%'
    }
  };

  function assetKey(src) {
    return ((src || '').split('/').pop() || '').replace(/\.svg(?:[?#].*)?$/i, '');
  }

  function upgradePhoto(img, index) {
    const key = assetKey(img.getAttribute('src'));
    const photo = photos[key];
    if (!photo) return;
    img.src = photo.src;
    img.alt = `${photo.alt} · 이야기 내용과 분리된 대표 실사 이미지`;
    img.dataset.photoRole = key;
    img.dataset.photoIndex = String(index + 1).padStart(2, '0');
    img.style.setProperty('--wf-photo-position', photo.position);
    if (!img.hasAttribute('loading') && !img.classList.contains('lead-image')) img.loading = 'lazy';
  }

  function upgradeVisibleArtwork() {
    const images = [...document.querySelectorAll('img')].filter((img) => /\.svg(?:[?#]|$)/i.test(img.getAttribute('src') || ''));
    images.forEach(upgradePhoto);
    document.documentElement.dataset.worldFeedArt = 'real-photo-workspace-v4';
    document.documentElement.dataset.photoArtwork = String(images.filter((img) => img.dataset.photoRole).length);
  }

  function markCurrentNavigation() {
    const route = (location.hash || '#feed').slice(1).split('?')[0];
    document.querySelectorAll('.product-nav [data-route-link]').forEach((link) => {
      const key = link.getAttribute('data-route-link');
      if (key === route || (route === 'story' && key === 'feed') || (route === 'why' && key === 'feed') || (route === 'preferences' && key === 'feed')) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  window.WorldFeedPhotoMap = photos;
  upgradeVisibleArtwork();
  markCurrentNavigation();
  window.addEventListener('hashchange', markCurrentNavigation);
})();
