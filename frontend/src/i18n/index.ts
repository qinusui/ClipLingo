import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zh from './zh.json';
import en from './en.json';

const saved = localStorage.getItem('ui_language') || 'zh';

i18n.use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
  },
  lng: saved,
  fallbackLng: 'zh',
  interpolation: { escapeValue: false },
});

export default i18n;
