import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const swogi = JSON.parse(fs.readFileSync(path.join(__dirname, 'swogi.json'), 'utf8'));
export const names_json = JSON.parse(fs.readFileSync(path.join(__dirname, 'names.json'), 'utf8'));
