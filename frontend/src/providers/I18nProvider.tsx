import React, { createContext, useContext, useMemo, useState } from 'react';
import { translations, SupportedLanguage } from '../i18n/translations';

type I18nContextValue = {
  language: SupportedLanguage;
  setLanguage: (lang: SupportedLanguage) => void;
  t: (key: string) => string;
};

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

export const I18nProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [language, setLanguage] = useState<SupportedLanguage>('ru');

  const value = useMemo<I18nContextValue>(() => {
    const dictionary = translations[language];
    const t = (key: string) => dictionary[key] ?? key;

    return { language, setLanguage, t };
  }, [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = () => {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error('useI18n must be used within I18nProvider');
  }

  return ctx;
};
