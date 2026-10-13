require('./bot.js');
require('./autopost.js');
process.on('uncaughtException', e => console.error('[Uncaught]', e.message));
process.on('unhandledRejection', e => console.error('[Unhandled]', e));
