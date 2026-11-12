# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "imageio-ffmpeg"]
# ///
"""Render generated slideshows: uv run scripts/experiment_video.py RUN_DIRECTORY/slideshow.

Uses installed Google Chrome by default. Produces one MP4 and timeline per HTML.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slideshow_directory', type=Path)
    parser.add_argument('--output', type=Path, help='Default: slideshow directory / videos')
    parser.add_argument('--chrome', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    parser.add_argument('--seconds', type=float, default=3.5, help='Seconds per change view')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    sources = sorted(args.slideshow_directory.glob('*.html'))
    if not sources:
        parser.error('No slideshow HTML files found')
    output = args.output or args.slideshow_directory / 'videos'
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chrome, headless=True, chromium_sandbox=True)
        try:
            for source in sources:
                render_video(browser, source, output, ffmpeg, args.seconds)
        finally:
            browser.close()


def render_video(browser, source, output, ffmpeg, seconds):
    page = browser.new_page(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(source.resolve().as_uri())
        page.evaluate("document.body.classList.add('recording')")
        count = page.evaluate('window.replay.count')
        timeline = []
        with tempfile.TemporaryDirectory(prefix='experiment-video-') as directory:
            temp = Path(directory)
            for index in range(count):
                page.evaluate('(index)=>window.replay.show(index)', index)
                page.evaluate('()=>document.fonts.ready')
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(resolve))')
                geometry = page.locator('#code').evaluate('(el)=>({width:el.clientWidth,fullWidth:el.scrollWidth,height:el.clientHeight,fullHeight:el.scrollHeight})')
                if geometry['fullWidth'] > geometry['width'] or geometry['fullHeight'] > geometry['height']:
                    raise ValueError(f'Clipped code in {source.name}, slide {index + 1}: {geometry}')
                if errors:
                    raise RuntimeError(errors)
                page.screenshot(path=str(temp / f'frame-{index:05}.png'))
                timeline.append(dict(slide=index + 1, start_seconds=index * seconds, caption=page.locator('#caption').inner_text()))
                print(f'{source.stem}: {index + 1}/{count}', flush=True)
            concat = temp / 'frames.txt'
            concat.write_text(''.join(f"file 'frame-{index:05}.png'\nduration {seconds}\n" for index in range(count)) + f"file 'frame-{count - 1:05}.png'\n")
            destination = output / f'{source.stem}.mp4'
            subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(concat), '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '30', '-movflags', '+faststart', str(destination)], check=True)
            subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(destination), '-f', 'null', '-'], check=True)
            destination.with_suffix('.timeline.json').write_text(json.dumps(dict(source=source.name, width=1920, height=1080, duration_seconds=count * seconds, slides=timeline), indent=2) + '\n')
            print(f'Verified: {destination}', flush=True)
    finally:
        page.close()


if __name__ == '__main__':
    main()
