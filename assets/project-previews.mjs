// One bounded download at a time. Covers stay visible until playback starts.
export function initProjectPreviews(root = document, env = window) {
    const finePointer = env.matchMedia('(hover: hover) and (pointer: fine)');
    const reducedMotion = env.matchMedia('(prefers-reduced-motion: reduce)');
    const entries = [...root.querySelectorAll('.project-card')].map(card => ({
        card, video: card.querySelector('video[data-preview]'), visible: false,
        wanted: false, skipBackground: false, failed: false, url: null, timer: null,
    })).filter(entry => entry.video);
    let active = null;
    let ready = false;
    let wakeTimer = null;
    const allowed = () => finePointer.matches && !reducedMotion.matches && !root.hidden;
    const backgroundAllowed = () => allowed() && !env.navigator.connection?.saveData
        && !['slow-2g', '2g'].includes(env.navigator.connection?.effectiveType);
    const showCover = entry => entry.card.classList.remove('is-preview-playing');
    const stop = entry => {
        showCover(entry);
        entry.video.pause();
        if (entry.video.readyState) entry.video.currentTime = 0;
    };
    function play(entry) {
        if (!entry.wanted || !allowed() || !entry.url) return;
        entry.video.src = entry.url;
        entry.video.play()?.catch(() => showCover(entry));
    }
    function schedule() {
        if (wakeTimer !== null) return;
        wakeTimer = env.setTimeout(() => { wakeTimer = null; pump(); }, 100);
    }
    function pump() {
        if (active || !allowed()) return;
        const next = entries.find(e => e.wanted && !e.url && !e.failed)
            || (ready && backgroundAllowed() && entries.find(e => e.visible && !e.url && !e.failed && !e.skipBackground));
        if (next) download(next);
    }
    async function download(entry) {
        const task = { entry, controller: new env.AbortController() };
        active = task;
        const timeout = env.setTimeout(() => task.controller.abort(), 30000);
        try {
            const response = await env.fetch(entry.video.dataset.preview, { signal: task.controller.signal, cache: 'default' });
            if (!response.ok) throw new Error('Preview unavailable');
            const blob = await response.blob();
            if (task.controller.signal.aborted) return;
            entry.url = env.URL.createObjectURL(blob);
            play(entry);
        } catch (error) {
            if (!task.controller.signal.aborted) entry.failed = true;
            else entry.skipBackground = true;
            showCover(entry);
        } finally {
            env.clearTimeout(timeout);
            if (active === task) active = null;
            // A timed-out hovered video must not start an unbounded retry loop.
            if (task.controller.signal.aborted && entry.wanted) entry.failed = true;
            schedule();
        }
    }
    for (const entry of entries) {
        entry.card.addEventListener('pointerenter', event => {
            if (event.pointerType === 'touch' || !allowed()) return;
            env.clearTimeout(entry.timer);
            entry.timer = env.setTimeout(() => {
                entry.wanted = true;
                entry.failed = false;
                if (entry.url) play(entry);
                else {
                    if (active && active.entry !== entry) active.controller.abort();
                    pump();
                }
            }, 160);
        });
        entry.card.addEventListener('pointerleave', () => {
            env.clearTimeout(entry.timer);
            entry.wanted = false;
            stop(entry);
            if (active?.entry === entry) {
                entry.skipBackground = true;
                active.controller.abort();
            }
            schedule();
        });
        entry.video.addEventListener('playing', () => {
            if (entry.wanted && allowed()) entry.card.classList.add('is-preview-playing');
            else stop(entry);
        });
        for (const event of ['waiting', 'stalled', 'error', 'emptied']) {
            entry.video.addEventListener(event, () => showCover(entry));
        }
    }
    const observer = new env.IntersectionObserver(changes => {
        for (const change of changes) {
            const entry = entries.find(e => e.card === change.target);
            entry.visible = change.isIntersecting;
            if (!entry.visible) {
                env.clearTimeout(entry.timer);
                entry.wanted = false;
                stop(entry);
                if (active?.entry === entry) active.controller.abort();
            }
        }
        schedule();
    }, { rootMargin: '80px', threshold: 0.01 });
    entries.forEach(e => observer.observe(e.card));
    const loaded = () => env.setTimeout(() => { ready = true; schedule(); }, 2000);
    if (root.readyState === 'complete') loaded();
    else env.addEventListener('load', loaded, { once: true });
    const suspend = () => {
        if (!allowed()) {
            active?.controller.abort();
            entries.forEach(e => { env.clearTimeout(e.timer); e.wanted = false; stop(e); });
        } else schedule();
    };
    root.addEventListener('visibilitychange', suspend);
    finePointer.addEventListener('change', suspend);
    reducedMotion.addEventListener('change', suspend);
    env.addEventListener('pagehide', event => {
        active?.controller.abort();
        entries.forEach(e => {
            env.clearTimeout(e.timer); e.wanted = false; stop(e);
            if (!event.persisted && e.url) env.URL.revokeObjectURL(e.url);
        });
    });
    return { entries, pump };
}
if (typeof document !== 'undefined') initProjectPreviews();
