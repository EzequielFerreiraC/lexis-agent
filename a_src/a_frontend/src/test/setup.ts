import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

// jsdom ainda não implementa <dialog>.showModal()/close().
const dialogo = HTMLDialogElement.prototype as Partial<HTMLDialogElement>;
if (!dialogo.showModal) {
  dialogo.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  dialogo.close = function close(this: HTMLDialogElement) {
    this.removeAttribute('open');
  };
}

// jsdom não rola a página: scrollTo só avisa "Not implemented" no log.
window.scrollTo = () => undefined;

Object.assign(URL, { createObjectURL: () => 'blob:teste', revokeObjectURL: () => undefined });

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
});
