// ============================================================================
// VIMA Auto-Post Bot — Firebase → Telegram Channel
// ============================================================================

const fs = require('fs');

const BOT_TOKEN   = process.env.BOT_TOKEN;
const CHANNEL     = process.env.TG_CHANNEL || 'https://t.me/Hitestpost';
const DB_URL      = process.env.FIREBASE_DB_URL || 'https://cineflix1-1fdc6-default-rtdb.firebaseio.com';
const API_KEY     = process.env.FIREBASE_API_KEY || 'AIzaSyAh6zMB65iWqt3R2Ep0C5_7eV8ZaUHI7t8';
const SEEN_DIR  = require('fs').existsSync('/data') ? '/data' : '/tmp';
const SEEN_FILE = SEEN_DIR + '/vima_seen.json';
const CHECK_EVERY = 2 * 60 * 1000; // 2 minutes

if (!BOT_TOKEN) { console.error('❌ BOT_TOKEN not set!'); process.exit(1); }

// ── Channel resolve ──
function resolveChannel(ch) {
  if (!ch) return null;
  ch = ch.trim();
  if (ch.startsWith('https://t.me/')) return '@' + ch.replace('https://t.me/', '').trim();
  return ch;
}
const CHANNEL_ID = resolveChannel(CHANNEL);

// ── Seen — Firebase ලෙස save (restart ලෙස persist වෙනවා) ──
async function loadSeen() {
  try {
    const r = await fetch(`${DB_URL}/bot_seen.json?key=${API_KEY}`);
    if (!r.ok) return new Set();
    const data = await r.json();
    if (!data || !Array.isArray(data)) return new Set();
    return new Set(data);
  } catch(e) { return new Set(); }
}
async function saveSeen(set) {
  try {
    await fetch(`${DB_URL}/bot_seen.json?key=${API_KEY}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([...set])
    });
  } catch(e) { console.error('[Seen] Save error:', e.message); }
}

// ── Firebase ──
async function fetchMovies() {
  const url = `${DB_URL}/movies.json?key=${API_KEY}&orderBy="$key"&limitToLast=20`;
  console.log(`[Firebase] Fetching: ${url}`);
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Firebase HTTP ${r.status}`);
  const data = await r.json();
  if (!data || typeof data !== 'object') return [];
  return Object.entries(data).map(([id, m]) => ({ id, ...(m||{}) }));
}

// ── Telegram ──
async function tg(method, body) {
  const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const d = await r.json();
  if (!d.ok) console.error(`[TG ${method}] Error:`, JSON.stringify(d));
  return d;
}

// ── Build caption ──
function buildCaption(m) {
  const title  = m.title || 'Unknown';
  const year   = m.year  || '';
  const isTV   = m.type==='tv' || m.type==='series' || m.type==='tv-series';
  const type   = isTV ? '📺 TV Series' : '🎬 Movie';
  const rating = m.rating || m.imdbRating || '';
  const genres = Array.isArray(m.genres) ? m.genres.slice(0,3).join(', ') : (m.genres||'');
  const lang   = m.language || '';
  const qual   = m.quality  || '';
  const story  = (m.story||m.description||'').replace(/\n/g,' ').slice(0,200);

  // Download links
  const dls = [];
  if (Array.isArray(m.downloads)) {
    m.downloads.forEach(d => {
      if (d.url  && d.url!=='#')  dls.push(`📥 [UsersDrive](${d.url})`);
      if (d.pd1080) dls.push(`🎞️ [1080p](${d.pd1080})`);
      if (d.pd720)  dls.push(`📽️ [720p](${d.pd720})`);
      if (d.pd480)  dls.push(`📱 [480p](${d.pd480})`);
      if (d.tgLink) dls.push(`✈️ [Telegram](${d.tgLink})`);
    });
  }

  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  const siteUrl = `https://moviemanialk.com/${isTV?'tv':'movie'}/${slug}${year?'-'+year:''}`;

  return `${type} *${title}*${year?' ('+year+')':''}
━━━━━━━━━━━━━━━━
${rating ? `⭐ *IMDb:* ${rating}\n` : ''}${genres ? `🎭 *Genres:* ${genres}\n` : ''}${lang   ? `🗣️ *Language:* ${lang}\n` : ''}${qual   ? `📺 *Quality:* ${qual}\n` : ''}━━━━━━━━━━━━━━━━
${story ? story+'\n━━━━━━━━━━━━━━━━\n' : ''}${dls.length ? '📥 *Downloads:*\n'+dls.join('\n')+'\n━━━━━━━━━━━━━━━━\n' : ''}🌐 [View on Movie Mania LK](${siteUrl})
_🎬 Movie Mania LK_`;
}

// ── Post ──
async function postMovie(m) {
  const caption = buildCaption(m);
  const poster  = m.poster || m.image || m.thumbnail || '';
  const kb = { inline_keyboard: [[
    { text: '🌐 View on Site', url: 'https://moviemanialk.com' }
  ]]};

  if (poster) {
    const res = await tg('sendPhoto', {
      chat_id: CHANNEL_ID,
      photo: poster,
      caption: caption.slice(0,1024),
      parse_mode: 'Markdown',
      reply_markup: kb
    });
    if (res.ok) return true;
    console.log('[Post] Photo failed, trying text...');
  }

  const res = await tg('sendMessage', {
    chat_id: CHANNEL_ID,
    text: caption.slice(0,4096),
    parse_mode: 'Markdown',
    disable_web_page_preview: false,
    reply_markup: kb
  });
  return res.ok;
}

// ══════════════════════════════════════
// MAIN
// ══════════════════════════════════════
let seen    = new Set();
let isFirst = true;

async function check() {
  try {
    console.log(`\n[${new Date().toISOString()}] Checking Firebase...`);
    const movies = await fetchMovies();
    console.log(`[Firebase] Got ${movies.length} movies`);

    if (isFirst) {
      // Load seen list from Firebase
      seen = await loadSeen();
      console.log(`[Seen] Loaded ${seen.size} seen movies from Firebase`);
      // Mark all existing as seen on startup
      let count = 0;
      movies.forEach(m => { if (!seen.has(m.id)) { seen.add(m.id); count++; } });
      await await saveSeen(seen);
      isFirst = false;
      console.log(`✅ Startup done. Marked ${count} movies as seen. Watching for new ones...`);

      // Test channel access
      const test = await tg('sendMessage', {
        chat_id: CHANNEL_ID,
        text: `✅ *VIMA Auto-Post Bot* started!\n🎬 Watching Movie Mania LK for new movies...\n_Powered by Gavesh Vimanshana_`,
        parse_mode: 'Markdown'
      });
      if (test.ok) console.log('✅ Channel test post OK!');
      else console.error('❌ Channel test FAILED:', test.description);
      return;
    }

    // Check for new
    const newOnes = movies.filter(m => !seen.has(m.id));
    if (!newOnes.length) {
      console.log('[Check] No new movies.');
      return;
    }

    console.log(`[Check] ${newOnes.length} new movie(s) found!`);
    for (const m of newOnes) {
      console.log(`[Post] Posting: ${m.title} (${m.id})`);
      const ok = await postMovie(m);
      if (ok) {
        seen.add(m.id);
        await saveSeen(seen);
        console.log(`✅ Posted: ${m.title}`);
      }
      await new Promise(r => setTimeout(r, 2000));
    }

  } catch(e) {
    console.error('[Error]', e.message);
  }
}

console.log('🌸 VIMA Auto-Post Bot starting...');
console.log(`📡 DB: ${DB_URL}`);
console.log(`📢 Channel: ${CHANNEL_ID}`);

check();
setInterval(check, CHECK_EVERY);
