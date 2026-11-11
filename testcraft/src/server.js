import { createApp } from './app.js';
import { seedIfEmpty } from './db.js';

const PORT = Number(process.env.PORT) || 3000;

seedIfEmpty();

const app = createApp();

app.listen(PORT, () => {
  console.log(`TestCraft running at http://localhost:${PORT}`);
});
