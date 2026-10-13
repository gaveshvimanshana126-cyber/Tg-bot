// VIMA Bot - Run autopost (bot.js optional)
require('./autopost.js');

// Keep process alive
process.on('uncaughtException', (e) => console.error('[Uncaught]', e.message));
process.on('unhandledRejection', (e) => console.error('[Unhandled]', e));
