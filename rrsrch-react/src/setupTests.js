// jest-dom's DOM matchers (toBeInTheDocument, toHaveTextContent...) on Vitest's expect.
import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// findBy*/waitFor give up after 1s by default, which a busy machine overruns on the bigger pages
configure({ asyncUtilTimeout: 3000 });
