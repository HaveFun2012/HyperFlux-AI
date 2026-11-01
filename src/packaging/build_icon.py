from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_LOGO = ROOT / "web" / "logo_hyperflux" / "hyperfluxdesktop.png"
SOURCE = (
    DESKTOP_LOGO
    if DESKTOP_LOGO.is_file()
    else ROOT / "web" / "logo_hyperflux" / "dark5.4.png"
)
DESTINATION = ROOT / "packaging" / "hyperflux.ico"


def main():
    with Image.open(SOURCE) as image:
        image = image.convert("RGBA")
        side = min(image.size)
        left = (image.width - side) // 2
        top = (image.height - side) // 2
        icon = image.crop((left, top, left + side, top + side))
        icon.save(DESTINATION, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


if __name__ == "__main__":
    main()
