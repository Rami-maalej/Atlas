import { createApp } from './app.js';
import { getDb } from './db.js';

const PORT = Number(process.env.PORT ?? 3000);

getDb(); // open + migrate + seed before serving traffic

const app = createApp();
const server = app.listen(PORT, () => {
  console.log(`TestHub running at http://localhost:${PORT}`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}
