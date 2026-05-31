/**
 * 轻量 toast 通知 — 替代 alert()，不会被浏览器弹窗拦截。
 *
 * 用法：
 *   import { toast } from './utils/toast';
 *   toast('操作成功');
 *   toast.error('操作失败');
 */

type ToastType = 'info' | 'error' | 'warning';

function show(message: string, type: ToastType = 'info', duration = 4000) {
  // 确保容器存在
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed top-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm';
    document.body.appendChild(container);
  }

  const el = document.createElement('div');
  const colorMap = {
    info: 'bg-blue-600',
    error: 'bg-red-600',
    warning: 'bg-amber-600',
  };
  el.className = `${colorMap[type]} text-white px-4 py-3 rounded-lg shadow-lg text-sm leading-snug opacity-0 translate-x-4 transition-all duration-300 cursor-pointer break-words`;
  el.textContent = message;

  // 点击关闭
  el.addEventListener('click', () => dismiss(el));

  container.appendChild(el);

  // 入场动画
  requestAnimationFrame(() => {
    el.classList.remove('opacity-0', 'translate-x-4');
    el.classList.add('opacity-100', 'translate-x-0');
  });

  // 自动消失
  if (duration > 0) {
    setTimeout(() => dismiss(el), duration);
  }
}

function dismiss(el: HTMLElement) {
  el.classList.remove('opacity-100', 'translate-x-0');
  el.classList.add('opacity-0', 'translate-x-4');
  setTimeout(() => el.remove(), 300);
}

export function toast(message: string, duration?: number) {
  show(message, 'info', duration);
}

toast.error = (message: string, duration?: number) => show(message, 'error', duration ?? 6000);
toast.warning = (message: string, duration?: number) => show(message, 'warning', duration ?? 5000);
