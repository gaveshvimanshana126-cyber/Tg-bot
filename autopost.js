// ============================================================================
// Movie Mania LK — Auto Post Bot
// Firebase RTDB ලෙස නව movies detect කරලා Telegram channel ලෙස auto post
// ============================================================================

const https = require('https');
const fs    = require('fs');

const BOT_TOKEN   = process.env.BOT_TOKEN;
const CHANNEL     = process.env.TG_CHANNEL || 'https://t.me/Hitestpost';
const DB_URL      = process.env.FIREBASE_DB_URL || 'https://cineflix1-1fdc6-default-rtdb.firebaseio.com';
const API_KEY     = process.env.FIREBASE_API_KEY || 'AIzaSyAh6zMB65iWqt3R2Ep0C5_7eV8ZaUHI7t8';
const SEEN_FILE   = '/tmp/vima_seen_movies.json';
const CHECK_EVERY = 2 * 60 * 1000; // 2 minutes

if (!BOT_TOKEN) { console.error('❌ BOT_TOKEN not set'); process.exit(1); }

// ── Channel ID resolve ──
// @username හෝ https://t.me/xxx → @username
function resolveChannel(ch) {
  if (!ch) return null;
  if (ch.startsWith('https://t.me/')) return '@' + ch.replace('https://t.me/', '');
  if (ch.startsWith('@')) return ch;
  return ch; // numeric id
}
const CHANNEL_ID = resolveChannel(CHANNEL);

// ── Seen movies persistence ──
function loadSeen() {
  try { return new Set(JSON.parse(fs.readFileSync(SEEN_FILE,'utf8'))); }
  catch(e) { return new Set(); }
}
function saveSeen(set) {
  try { fs.writeFileSync(SEEN_FILE, JSON.stringify([...set])); } catch(e){}
}

// ── Firebase fetch ──
async function fetchMovies() {
  const url = `${DB_URL}/movies.json?key=${API_KEY}&orderBy="$key"&limitToLast=30`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Firebase ${r.status}`);
  const data = await r.json();
  if (!data) return [];
  return Object.entries(data).map(([id, m]) => ({ id, ...m }));
}

// ── Format post ──
function buildCaption(m) {
  const title   = m.title || 'Unknown';
  const year    = m.year  || '';
  const type    = (m.type==='tv'||m.type==='series') ? '📺 TV Series' : '🎬 Movie';
  const lang    = m.language || '';
  const quality = m.quality  || '';
  const rating  = m.rating   || m.imdbRating || '';
  const genres  = Array.isArray(m.genres) ? m.genres.join(', ') : (m.genres||'');
  const story   = (m.story||m.description||'').slice(0,300);

  // Download links
  const dlLines = [];
  if (Array.isArray(m.downloads)) {
    m.downloads.forEach(d => {
      if (d.url && d.url !== '#') dlLines.push(`📥 [Download](${d.url})`);
      if (d.pd1080) dlLines.push(`🎞️ [1080p](${d.pd1080})`);
      if (d.pd720)  dlLines.push(`📽️ [720p](${d.pd720})`);
      if (d.pd480)  dlLines.push(`📱 [480p](${d.pd480})`);
      if (d.tgLink) dlLines.push(`✈️ [Telegram](${d.tgLink})`);
    });
  }
  if (m.downloadLink) dlLines.push(`📥 [Download](${m.downloadLink})`);

  const siteLink = `https://moviemanialk.com/${(m.type==='tv'||m.type==='series')?'tv':'movie'}/${
    (title.toLowerCase().replace(/[^a-z0-9]+/g,'-'))}${year?'-'+year:''}`;

  return `${type} | *${title}*${year?' ('+year+')':''}
━━━━━━━━━━━━━━━━━━
${rating   ? `⭐ *Rating:* ${rating}\n` : ''}${genres    ? `🎭 *Genres:* ${genres}\n` : ''}${lang      ? `🗣️ *Language:* ${lang}\n` : ''}${quality   ? `📺 *Quality:* ${quality}\n` : ''}━━━━━━━━━━━━━━━━━━
${story ? story+'...\n━━━━━━━━━━━━━━━━━━\n' : ''}${dlLines.length ? dlLines.join('\n')+'\n━━━━━━━━━━━━━━━━━━\n' : ''}🌐 [Movie Mania LK](${siteLink})

🎬 *Movie Mania LK* | @${CHANNEL_ID.replace('@','')}`;
}

// ── Telegram API ──
async function tgRequest(method, body) {
  const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return r.json();
}

async function postToChannel(movie) {
  const caption = buildCaption(movie);
  const poster  = movie.poster || movie.image || movie.thumbnail || '';

  let res;
  if (poster) {
    res = await tgRequest('sendPhoto', {
      chat_id:    CHANNEL_ID,
      photo:      poster,
      caption:    caption.slice(0, 1024),
      parse_mode: 'Markdown',
      reply_markup: {
        inline_keyboard: [[
          { text: '🌐 View on Site', url: `https://moviemanialk.com` },
          { text: '🎬 More Movies',  url: `https://t.me/${CHANNEL_ID.replace('@','')}` }
        ]]
      }
    });
  }

  // If no poster or photo failed, send text
  if (!poster || !res?.ok) {
    res = await tgRequest('sendMessage', {
      chat_id:              CHANNEL_ID,
      text:                 caption.slice(0, 4096),
      parse_mode:           'Markdown',
      disable_web_page_preview: false,
      reply_markup: {
        inline_keyboard: [[
          { text: '🌐 View on Site', url: `https://moviemanialk.com` },
          { text: '🎬 More Movies',  url: `https://t.me/${CHANNEL_ID.replace('@','')}` }
        ]]
      }
    });
  }

  return res;
}

// ══════════════════════════════════════════
// MAIN LOOP
// ══════════════════════════════════════════
let seen = loadSeen();
let isFirst = true;

async function checkAndPost() {
  try {
    const movies = await fetchMovies();
    const newMovies = [];

    for (const m of movies) {
      if (!seen.has(m.id)) {
        newMovies.push(m);
      }
    }

    // First run — just mark all as seen, don't post old ones
    if (isFirst) {
      movies.forEach(m => seen.add(m.id));
      saveSeen(seen);
      isFirst = false;
      console.log(`✅ Bot started. Watching ${movies.length} movies. New ones will be posted to ${CHANNEL_ID}`);
      return;
    }

    if (newMovies.length === 0) {
      console.log(`[${new Date().toLocaleTimeString()}] No new movies.`);
      return;
    }

    // Post each new movie (newest last = shows at top in channel)
    for (const m of newMovies) {
      try {
        const res = await postToChannel(m);
        if (res.ok) {
          console.log(`✅ Posted: ${m.title} (${m.id})`);
          seen.add(m.id);
          saveSeen(seen);
          // Small delay between posts
          await new Promise(r => setTimeout(r, 1500));
        } else {
          console.error(`❌ Failed to post ${m.id}:`, res.description);
        }
      } catch(e) {
        console.error(`❌ Error posting ${m.id}:`, e.message);
      }
    }

  } catch(e) {
    console.error(`❌ Check error:`, e.message);
  }
}

// Start
console.log('🌸 VIMA Auto-Post Bot starting...');
console.log(`📡 Firebase: ${DB_URL}`);
console.log(`📢 Channel: ${CHANNEL_ID}`);
console.log(`⏱️ Check interval: ${CHECK_EVERY/1000}s`);

checkAndPost();
setInterval(checkAndPost, CHECK_EVERY);
