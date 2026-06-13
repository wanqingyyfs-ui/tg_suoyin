// @ts-check
import { defineConfig } from 'astro/config';

const site = process.env.SITE_URL || 'https://tg-suoyin.vercel.app';

// https://astro.build/config
export default defineConfig({
  site,
});
