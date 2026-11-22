import path from 'node:path';
import { defineConfig, mergeConfig } from 'vite';
import desktop from './vite.config';

export default mergeConfig(
  desktop,
  defineConfig({
    root: path.resolve(__dirname, 'mobile'),
    publicDir: path.resolve(__dirname, 'public'),
    server: { port: 3001, fs: { allow: [__dirname] } },
    build: {
      outDir: path.resolve(__dirname, 'dist-mobile'),
      emptyOutDir: true,
      // Both apps have the same public base. Unique asset paths prevent collisions.
      assetsDir: 'mobile-assets',
    },
  }),
);
