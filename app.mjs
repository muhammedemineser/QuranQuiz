import {
  getNextLockedVerse,
  buildQuestionOptions,
  applyCorrectAnswer,
  computeSurahProgress,
} from './quizLogic.mjs';

const USERS_API_URL = 'https://sluglike-clarence-agential.ngrok-free.dev/users';
const USERS_CACHE_KEY = 'quranquiz_users_cache_v1';
const QURAN_CACHE_KEY = 'quranquiz_quran_cache_v1';
const DISTRACTOR_CACHE_KEY = 'quranquiz_distractor_cache_v1';
const SESSION_KEY = 'quranquiz_session_user_v1';

const state = {
  users: [],
  quranData: null,
  distractorCache: {},
  allVersesByIndex: {},
  currentUser: null,
  currentSurah: 1,
  unlockedBySurah: {},
  question: null,
};

const loginView = document.getElementById('loginView');
const appView = document.getElementById('appView');
const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const registerBox = document.getElementById('registerBox');
const registerForm = document.getElementById('registerForm');
const registerError = document.getElementById('registerError');
const regUsernameInput = document.getElementById('regUsername');
const regPasswordInput = document.getElementById('regPassword');
const backToLoginBtn = document.getElementById('backToLoginBtn');
const navActions = document.getElementById('navActions');
const surahList = document.getElementById('surahList');
const surahSearch = document.getElementById('surahSearch');
const surahName = document.getElementById('surahName');
const userBadge = document.getElementById('userBadge');
const playBtn = document.getElementById('playBtn');
const openProgressBtn = document.getElementById('openProgressBtn');
const mushafPanel = document.getElementById('mushafPanel');
const progressPanel = document.getElementById('progressPanel');
const verseGrid = document.getElementById('verseGrid');
const progressRows = document.getElementById('progressRows');
const resetAllBtn = document.getElementById('resetAllBtn');
const basmala = document.getElementById('basmala');
const quizModal = document.getElementById('quizModal');
const modalPrompt = document.getElementById('modalPrompt');
const optionList = document.getElementById('optionList');
const nextBtn = document.getElementById('nextBtn');
const closeModalBtn = document.getElementById('closeModalBtn');
const burgerBtn = document.getElementById('burgerBtn');
const sidebar = document.querySelector('.sidebar');

burgerBtn.addEventListener('click', () => {
  sidebar.classList.toggle('collapsed');
  burgerBtn.classList.toggle('open');
});

bootstrap().catch((error) => {
  console.error(error);
  loginError.textContent = 'Initialisierung fehlgeschlagen. Bitte Seite neu laden.';
});

async function bootstrap() {
  await Promise.all([loadUsersToCache(), loadQuranToCache(), loadDistractorCache()]);

  const storedSession = localStorage.getItem(SESSION_KEY);
  if (storedSession) {
    const sessionUser = JSON.parse(storedSession);
    const match = state.users.find((user) => String(user.id) === String(sessionUser.id));
    if (match) {
      setCurrentUser(match);
      showApp();
      return;
    }
  }

  showLogin();
}

async function loadUsersToCache() {
  const cached = localStorage.getItem(USERS_CACHE_KEY);
  if (cached) {
    state.users = JSON.parse(cached);
    return;
  }

  const response = await fetch(USERS_API_URL, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error('users fetch failed');
  }
  const users = await response.json();
  state.users = users;
  localStorage.setItem(USERS_CACHE_KEY, JSON.stringify(users));
}

async function loadQuranToCache() {
  const cached = localStorage.getItem(QURAN_CACHE_KEY);
  if (cached) {
    state.quranData = JSON.parse(cached);
  } else {
    const response = await fetch('./data/quran-data.json', { cache: 'force-cache' });
    if (!response.ok) {
      throw new Error('quran data fetch failed');
    }
    state.quranData = await response.json();
    localStorage.setItem(QURAN_CACHE_KEY, JSON.stringify(state.quranData));
  }

  for (const verses of Object.values(state.quranData.versesBySurah)) {
    for (const verse of verses) {
      state.allVersesByIndex[verse.verse_index] = verse;
    }
  }
}

async function loadDistractorCache() {
  const cached = localStorage.getItem(DISTRACTOR_CACHE_KEY);
  if (cached) {
    state.distractorCache = JSON.parse(cached);
    return;
  }

  const response = await fetch('./django-project/quiz/cache/distractor_cache.json', { cache: 'force-cache' });
  if (!response.ok) {
    console.warn('Distractor cache nicht gefunden – fällt auf Zufallsauswahl zurück.');
    return;
  }

  const payload = await response.json();
  state.distractorCache = payload.distractors ?? {};
  localStorage.setItem(DISTRACTOR_CACHE_KEY, JSON.stringify(state.distractorCache));
}

loginForm.addEventListener('submit', (event) => {
  event.preventDefault();
  loginError.textContent = '';

  const entered = usernameInput.value.trim().toLowerCase();
  const enteredPassword = passwordInput.value;

  if (!entered) {
    loginError.textContent = 'Username erforderlich.';
    return;
  }

  const user = state.users.find((item) => {
    const candidates = [item.username, item.name].filter(Boolean).map((value) => String(value).toLowerCase());
    return candidates.includes(entered);
  });

  if (!user) {
    loginError.textContent = 'User nicht gefunden. Registriere dich hier:';
    regUsernameInput.value = usernameInput.value.trim();
    registerBox.hidden = false;
    return;
  }

  if (user.password && user.password !== enteredPassword) {
    loginError.textContent = 'Falsches Passwort.';
    return;
  }

  setCurrentUser(user);
  showApp();
});

backToLoginBtn.addEventListener('click', () => {
  registerBox.hidden = true;
  registerError.textContent = '';
  loginError.textContent = '';
});

registerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  registerError.textContent = '';

  const username = regUsernameInput.value.trim();
  const password = regPasswordInput.value;

  if (!username) {
    registerError.textContent = 'Username erforderlich.';
    return;
  }
  if (!password) {
    registerError.textContent = 'Passwort erforderlich.';
    return;
  }

  const exists = state.users.some(
    (u) => String(u.username || '').toLowerCase() === username.toLowerCase(),
  );
  if (exists) {
    registerError.textContent = 'Username bereits vergeben.';
    return;
  }

  const response = await fetch(USERS_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    registerError.textContent = 'Registrierung fehlgeschlagen.';
    return;
  }

  const newUser = await response.json();
  state.users.push(newUser);
  localStorage.setItem(USERS_CACHE_KEY, JSON.stringify(state.users));

  registerBox.hidden = true;
  setCurrentUser(newUser);
  showApp();
});

surahSearch.addEventListener('input', () => {
  renderSurahList(surahSearch.value.trim());
});

playBtn.addEventListener('click', openQuestion);
openProgressBtn.addEventListener('click', () => {
  mushafPanel.classList.remove('active');
  progressPanel.classList.add('active');
  renderProgress();
});

resetAllBtn.addEventListener('click', () => {
  if (!confirm('Reset all progress?')) return;
  state.unlockedBySurah = {};
  persistProgress();
  renderMushaf();
  renderProgress();
});

nextBtn.addEventListener('click', openQuestion);
closeModalBtn.addEventListener('click', () => closeModal());

function setCurrentUser(user) {
  state.currentUser = user;
  localStorage.setItem(SESSION_KEY, JSON.stringify({ id: user.id }));
  state.unlockedBySurah = readProgress();
}

function showLogin() {
  loginView.classList.add('active');
  appView.classList.remove('active');
  navActions.innerHTML = '';
}

function showApp() {
  loginView.classList.remove('active');
  appView.classList.add('active');

  navActions.innerHTML = '';
  const logoutBtn = document.createElement('button');
  logoutBtn.type = 'button';
  logoutBtn.className = 'btn btn-outline';
  logoutBtn.textContent = 'Logout';
  logoutBtn.addEventListener('click', () => {
    localStorage.removeItem(SESSION_KEY);
    state.currentUser = null;
    state.unlockedBySurah = {};
    showLogin();
  });
  navActions.appendChild(logoutBtn);

  const userLabel = state.currentUser.username || state.currentUser.name || state.currentUser.id;
  userBadge.textContent = `@${userLabel}`;

  mushafPanel.classList.add('active');
  progressPanel.classList.remove('active');
  renderSurahList('');
  renderMushaf();
}

function readProgress() {
  if (!state.currentUser) return {};
  const key = progressKey();
  const payload = localStorage.getItem(key);
  return payload ? JSON.parse(payload) : {};
}

function persistProgress() {
  localStorage.setItem(progressKey(), JSON.stringify(state.unlockedBySurah));
}

function progressKey() {
  return `quranquiz_progress_${state.currentUser.id}`;
}

function getCurrentVerses() {
  return state.quranData.versesBySurah[String(state.currentSurah)] || [];
}

function getUnlockedUpTo() {
  return Number(state.unlockedBySurah[String(state.currentSurah)] || 0);
}

function setUnlockedUpTo(value) {
  state.unlockedBySurah[String(state.currentSurah)] = value;
  persistProgress();
}

function renderSurahList(query) {
  const normalized = query.toLowerCase();
  const fragment = document.createDocumentFragment();

  state.quranData.chapters
    .filter((chapter) => {
      if (!normalized) return true;
      return (
        String(chapter.chapter_number) === normalized ||
        chapter.chapter_name.toLowerCase().includes(normalized)
      );
    })
    .forEach((chapter) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'surah-item';
      if (chapter.chapter_number === state.currentSurah) {
        button.classList.add('active');
      }
      button.innerHTML = `<span class="num">${chapter.chapter_number}</span><span>${escapeHtml(chapter.chapter_name)}</span>`;
      button.addEventListener('click', () => {
        state.currentSurah = chapter.chapter_number;
        mushafPanel.classList.add('active');
        progressPanel.classList.remove('active');
        renderSurahList(surahSearch.value.trim());
        renderMushaf();
      });
      fragment.appendChild(button);
    });

  surahList.innerHTML = '';
  surahList.appendChild(fragment);
}

function renderMushaf() {
  const chapter = state.quranData.chapters.find((item) => item.chapter_number === state.currentSurah);
  surahName.textContent = chapter ? chapter.chapter_name : `Surah ${state.currentSurah}`;
  basmala.style.display = state.currentSurah === 9 ? 'none' : 'block';

  const unlockedUpTo = getUnlockedUpTo();
  const verses = getCurrentVerses();
  const fragment = document.createDocumentFragment();

  for (const verse of verses) {
    const token = document.createElement('span');
    token.className = 'verse';
    token.classList.add(verse.verse_index <= unlockedUpTo ? 'unlocked' : 'locked');
    token.dataset.index = String(verse.verse_index);
    token.innerHTML = `<span>${escapeHtml(verse.text_ar)}</span><span class="verse-num">﴿${verse.verse_number}﴾</span>`;
    fragment.appendChild(token);
  }

  verseGrid.innerHTML = '';
  verseGrid.appendChild(fragment);
}

function renderProgress() {
  const fragment = document.createDocumentFragment();

  for (const chapter of state.quranData.chapters) {
    const verses = state.quranData.versesBySurah[String(chapter.chapter_number)] || [];
    const unlockedUpTo = Number(state.unlockedBySurah[String(chapter.chapter_number)] || 0);
    const progress = computeSurahProgress(verses, unlockedUpTo);

    const row = document.createElement('div');
    row.className = 'progress-row';
    row.innerHTML = `
      <div>${chapter.chapter_number}</div>
      <div>
        <div dir="rtl">${escapeHtml(chapter.chapter_name)}</div>
        <div class="bar"><span style="width:${progress.pct}%"></span></div>
      </div>
      <div>${progress.pct}%</div>
      <button class="btn btn-outline" type="button">↺</button>
    `;

    const resetBtn = row.querySelector('button');
    resetBtn.addEventListener('click', () => {
      state.unlockedBySurah[String(chapter.chapter_number)] = 0;
      persistProgress();
      if (chapter.chapter_number === state.currentSurah) {
        renderMushaf();
      }
      renderProgress();
    });

    fragment.appendChild(row);
  }

  progressRows.innerHTML = '';
  progressRows.appendChild(fragment);
}

function openQuestion() {
  const verses = getCurrentVerses();
  const unlockedUpTo = getUnlockedUpTo();
  const nextVerse = getNextLockedVerse(verses, unlockedUpTo);

  nextBtn.style.display = 'none';
  optionList.innerHTML = '';

  if (!nextVerse) {
    modalPrompt.textContent = 'Surah complete.';
    const done = document.createElement('div');
    done.textContent = 'Alle Verse in dieser Surah sind freigeschaltet.';
    optionList.appendChild(done);
    openModal();
    return;
  }

  state.question = {
    correctIndex: nextVerse.verse_index,
    verseNumber: nextVerse.verse_number,
  };

  modalPrompt.textContent = `Vers ${nextVerse.verse_number}`;

  const options = buildQuestionOptions(nextVerse, state.allVersesByIndex, state.distractorCache, 4);
  options.forEach((option) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'option-btn';
    btn.textContent = option.text_ar;
    btn.addEventListener('click', () => submitAnswer(btn, option.verse_index));
    optionList.appendChild(btn);
  });

  openModal();
}

function submitAnswer(button, chosenIndex) {
  const buttons = Array.from(optionList.querySelectorAll('.option-btn'));
  buttons.forEach((btn) => {
    btn.disabled = true;
  });

  const oldUnlocked = getUnlockedUpTo();
  const nextUnlocked = applyCorrectAnswer(oldUnlocked, chosenIndex, state.question.correctIndex);
  const isCorrect = nextUnlocked !== oldUnlocked;

  if (isCorrect) {
    button.classList.add('correct');
    setUnlockedUpTo(nextUnlocked);
    renderMushaf();
    nextBtn.style.display = 'inline-block';
  } else {
    button.classList.add('wrong');
    buttons.forEach((btn) => {
      if (btn !== button) {
        btn.disabled = false;
      }
    });
  }
}

function openModal() {
  quizModal.classList.add('open');
}

function closeModal() {
  quizModal.classList.remove('open');
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
