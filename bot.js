const TelegramBot = require('node-telegram-bot-api');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const API_KEY  = 'chama_api_3d72ec318aaf94313008eff7e38f3fbe';
const LKSUB    = 'https://api.chamindu.site/api/v1/movies/lksub';
const CINEMX   = 'https://api.chamindu.site/api/v1/movies/cinemx';

const bot = new TelegramBot(TOKEN, { polling: true });
console.log('🤖 Bot started...');

const userState = {};

// ══════════════════════════════════════════════
// DOWNLOAD FILE (for small files like SRT/ZIP)
// ══════════════════════════════════════════════
function downloadFile(url, ext) {
  return new Promise((resolve, reject) => {
    const tmp = path.join(os.tmpdir(), 'dl_' + Date.now() + (ext || '.bin'));
    const file = fs.createWriteStream(tmp);
    function doGet(u, hops=0) {
      if (hops > 5) return reject(new Error('Too many redirects'));
      const proto = u.startsWith('https') ? https : http;
      proto.get(u, { headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://cinemx.lk/' } }, (res) => {
        if ([301,302,307,308].includes(res.statusCode) && res.headers.location)
          return doGet(res.headers.location, hops+1);
        if (res.statusCode !== 200) return reject(new Error('HTTP ' + res.statusCode));
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(tmp); });
        file.on('error', reject);
      }).on('error', reject);
    }
    doGet(url);
  });
}

// ══════════════════════════════════════════════
// API
// ══════════════════════════════════════════════
async function apiGet(url) {
  const r = await fetch(url); return r.json();
}

async function cinemxSearch(q) {
  const d = await apiGet(`${CINEMX}/search?q=${encodeURIComponent(q)}&api_key=${API_KEY}`);
  return d.status ? (d.data||[]).map(x=>({...x,_src:'cinemx'})) : [];
}
async function cinemxDetail(link) {
  const d = await apiGet(`${CINEMX}/infodl?q=${encodeURIComponent(link)}&api_key=${API_KEY}`);
  return d.status ? {...d.data, _src:'cinemx'} : null;
}
async function lksubSearch(q) {
  const d = await apiGet(`${LKSUB}/search?q=${encodeURIComponent(q)}&api_key=${API_KEY}`);
  return d.status ? (d.data||[]).map(x=>({...x,_src:'lksub'})) : [];
}
async function lksubDetail(link) {
  const d = await apiGet(`${LKSUB}/infodl?q=${encodeURIComponent(link)}&api_key=${API_KEY}`);
  return d.status ? {...d.data, _src:'lksub'} : null;
}

// ══════════════════════════════════════════════
// COMMANDS
// ══════════════════════════════════════════════
bot.onText(/\/start/, (msg) => {
  const name = msg.from.first_name || 'යාළුවා';
  bot.sendMessage(msg.chat.id,
`👋 හෙලෝ *${name}*!

🎬 *Sinhala Subtitles Bot* ❤️

Movie name ලියලා send කරන්න!

📦 *Sources:*
🎞️ CineMX — Movie + Subtitles
📦 LKSubs — Subtitle ZIPs

/help /id`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📋 *Help*

Movie name type කරලා send කරන්න
Results list ලෙස select කරන්න

🎞️ *CineMX:*
• 4K / 1080p / 720p / 480p download links
• Sinhala + English subtitle links

📦 *LKSubs:*
• Subtitle ZIP direct download`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `🆔 Chat ID: \`${msg.chat.id}\`\nUser ID: \`${msg.from.id}\``,
    { parse_mode: 'Markdown' }
  );
});

// ══════════════════════════════════════════════
// SEARCH
// ══════════════════════════════════════════════
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;
  const chatId = msg.chat.id;
  const query  = msg.text.trim();

  const st = await bot.sendMessage(chatId, `🔍 *"${query}"* සෙවිල්ලා... ⏳`, { parse_mode: 'Markdown' });

  try {
    const [cx, lk] = await Promise.allSettled([cinemxSearch(query), lksubSearch(query)]);
    const all = [
      ...(cx.status==='fulfilled' ? cx.value : []),
      ...(lk.status==='fulfilled' ? lk.value : [])
    ];

    if (!all.length) {
      return bot.editMessageText(`😔 *"${query}"* — results නෑ.\nවෙනත් title try කරන්න.`,
        { chat_id: chatId, message_id: st.message_id, parse_mode: 'Markdown' });
    }

    userState[chatId] = { results: all };

    const kb = all.slice(0,8).map((r,i) => {
      const icon = r._src==='cinemx' ? '🎞️' : '📦';
      const name = (r.title||'').replace(/ (With |)\bSinhala\b.*/i,'').replace(/\[.*\]/,'').trim();
      const yr   = r.year ? ` (${r.year})` : '';
      return [{ text:`${icon} ${name}${yr}`, callback_data:`pick_${i}` }];
    });

    bot.editMessageText(
      `✅ *${all.length}* result(s)\n🎞️ CineMX  📦 LKSubs\n\nSelect:`,
      { chat_id: chatId, message_id: st.message_id, parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: kb } }
    );
  } catch(e) {
    bot.editMessageText(`❌ ${e.message}`, { chat_id: chatId, message_id: st.message_id });
  }
});

// ══════════════════════════════════════════════
// CALLBACKS
// ══════════════════════════════════════════════
bot.on('callback_query', async (cb) => {
  const chatId = cb.message.chat.id;
  const msgId  = cb.message.message_id;
  const data   = cb.data;
  await bot.answerCallbackQuery(cb.id);

  // ── Pick movie ──
  if (data.startsWith('pick_')) {
    const idx  = parseInt(data.replace('pick_',''));
    const item = userState[chatId]?.results?.[idx];
    if (!item) return;

    await bot.editMessageText(`⏳ Loading...`, { chat_id: chatId, message_id: msgId });

    try {
      const detail = item._src==='cinemx'
        ? await cinemxDetail(item.link)
        : await lksubDetail(item.link);
      if (!detail) throw new Error('Details failed');

      userState[chatId].detail = detail;

      const title   = (detail.title||'').replace(/ (With |)\bSinhala\b.*/i,'').replace(/\[.*\]/,'').trim();
      const genres  = Array.isArray(detail.genres) ? detail.genres.join(', ') : (detail.genres||'N/A');
      const cast    = (detail.cast||[]).slice(0,5).join(', ') || 'N/A';
      const dur     = detail.duration ? `⏱ *Duration:* ${detail.duration}\n` : '';
      const qual    = detail.quality  ? `📺 *Quality:* ${detail.quality}\n`  : '';
      const dir     = detail.director ? `🎬 *Director:* ${detail.director}\n`: '';
      const lang    = detail.language ? `🗣 *Language:* ${detail.language}\n` : '';
      const story   = (detail.story||'').slice(0,300);

      let dlBtns = [];

      if (item._src === 'cinemx') {
        // Group: movies + subtitles
        const movies = (detail.downloads||[]).filter(d=>!d.quality?.includes('SRT'));
        const subs   = (detail.downloads||[]).filter(d=> d.quality?.includes('SRT'));

        movies.forEach((d,i) => {
          dlBtns.push([{ text:`🎬 ${d.name||d.title} ${d.size&&d.size!=='N/A'?'['+d.size+']':''}`.trim(),
            callback_data:`cxmov_${i}` }]);
        });
        subs.forEach((d,i) => {
          const isSi = d.name?.toLowerCase().includes('sinhala')||d.title?.toLowerCase().includes('sinhala');
          dlBtns.push([{ text:`${isSi?'🇱🇰':'🇬🇧'} ${d.name||d.title}`,
            callback_data:`cxsub_${i}` }]);
        });
        dlBtns.push([{ text:'🌐 CineMX ලෙස බලන්න', url: item.link }]);
      } else {
        // LKSubs
        (detail.downloads||[]).forEach((d,i)=>{
          const isZip = d.link?.includes('.zip');
          dlBtns.push([{ text: isZip ? `📥 Subtitle ZIP Download` : `🎬 ${d.name}`,
            callback_data: isZip ? `lkzip_${i}` : `lkext_${i}` }]);
        });
        dlBtns.push([{ text:'🌐 LKSubs ලෙස බලන්න', url: item.link }]);
      }

      const caption =
`🎬 *${title}*
⭐ *IMDb:* ${detail.imdb||'N/A'}  📅 *Year:* ${detail.year||'N/A'}
🎭 *Genres:* ${genres}
${dur}${qual}${dir}${lang}👥 *Cast:* ${cast}

📖 ${story}${story.length>=300?'...':''}

📥 *Downloads:*`;

      await bot.deleteMessage(chatId, msgId).catch(()=>{});
      const img = detail.image || item.image;
      if (img) {
        await bot.sendPhoto(chatId, img, {
          caption: caption.slice(0,1024),
          parse_mode:'Markdown',
          reply_markup:{ inline_keyboard: dlBtns }
        });
      } else {
        await bot.sendMessage(chatId, caption, {
          parse_mode:'Markdown',
          reply_markup:{ inline_keyboard: dlBtns }
        });
      }
    } catch(e) {
      console.error(e);
      bot.sendMessage(chatId, `❌ Error: ${e.message}\n🔗 ${item.link}`);
    }
  }

  // ── CineMX movie link ──
  if (data.startsWith('cxmov_')) {
    const i = parseInt(data.replace('cxmov_',''));
    const dl = (userState[chatId]?.detail?.downloads||[])
      .filter(d=>!d.quality?.includes('SRT'))[i];
    if (!dl) return;
    bot.sendMessage(chatId,
      `🎬 *${dl.name||dl.title}*\n${dl.size&&dl.size!=='N/A'?`📦 Size: ${dl.size}\n`:''}\n🔗 [Download Link](${dl.link})\n\n_Browser / IDM ලෙස open කරලා download කරන්න_`,
      { parse_mode:'Markdown', disable_web_page_preview:true }
    );
  }

  // ── CineMX subtitle link ──
  if (data.startsWith('cxsub_')) {
    const i = parseInt(data.replace('cxsub_',''));
    const subs = (userState[chatId]?.detail?.downloads||[])
      .filter(d=>d.quality?.includes('SRT'));
    const dl = subs[i];
    if (!dl) return;
    // Try direct download first, fallback to link
    await sendFileOrLink(chatId, dl.link, '.srt', `📝 *${dl.name||dl.title}*`);
  }

  // ── LKSubs ZIP ──
  if (data.startsWith('lkzip_')) {
    const i = parseInt(data.replace('lkzip_',''));
    const dl = (userState[chatId]?.detail?.downloads||[])[i];
    if (!dl) return;
    await sendFileOrLink(chatId, dl.link, '.zip', `📥 *Sinhala Subtitle ZIP*`);
  }

  // ── LKSubs external ──
  if (data.startsWith('lkext_')) {
    const i = parseInt(data.replace('lkext_',''));
    const dl = (userState[chatId]?.detail?.downloads||[])[i];
    if (!dl) return;
    bot.sendMessage(chatId,
      `🎬 *${dl.name}*\n\n🔗 [Download Link](${dl.link})`,
      { parse_mode:'Markdown', disable_web_page_preview:true }
    );
  }
});

// ══════════════════════════════════════════════
// SEND FILE OR FALLBACK TO LINK
// ══════════════════════════════════════════════
async function sendFileOrLink(chatId, url, ext, caption) {
  const st = await bot.sendMessage(chatId, `⏳ Downloading...`);
  try {
    const fp = await downloadFile(url, ext);
    const mb = (fs.statSync(fp).size/1024/1024).toFixed(2);
    await bot.editMessageText(`📦 Sending (${mb} MB)...`, { chat_id:chatId, message_id:st.message_id });
    await bot.sendDocument(chatId, fp, { caption, parse_mode:'Markdown' });
    fs.unlinkSync(fp);
    bot.deleteMessage(chatId, st.message_id).catch(()=>{});
  } catch(e) {
    console.error('sendFile error:', e.message);
    bot.editMessageText(
      `⚠️ Bot direct download failed.\n\n📎 *Manual download:*\n[Click here](${url})\n\n_Browser ලෙස open කරලා download කරන්න_`,
      { chat_id:chatId, message_id:st.message_id, parse_mode:'Markdown', disable_web_page_preview:true }
    );
  }
}

bot.on('polling_error', (e) => console.error('Polling:', e.message));
