# Imposter

A bilingual desktop social-deduction game built with Python and PyQt6. One computer hosts the game while players use their phones to scan individual QR codes and privately reveal their role or secret word.

## Features

- English and Arabic interfaces with right-to-left layout support
- Configurable player and imposter counts
- Private phone-based role reveal through generated QR codes
- Optional hints for imposters
- Elimination rounds, meeting timer, and win-state tracking
- Multiple selectable word categories with custom artwork
- Companion desktop manager for editing categories, bilingual words, hints, and images

## Preview

![Animals category](assets/animals.png)
![Food category](assets/food.png)
![Party category](assets/party_time.png)

## Run Locally

Requirements: Python 3.11+.

```bash
python -m pip install -r requirements.txt
python main.py
```

The repository includes a small bilingual sample word pack. Run the companion manager with:

```bash
python content_manager.py
```

## Validate and Test

```bash
python validate_words.py --strict
python -m unittest discover -s tests -v
```

## Project Structure

- `main.py`: game interface and round logic
- `content_manager.py`: category and word-pack editor
- `data/words.json`: sample bilingual content
- `validate_words.py`: content schema validator
- `tests/`: automated model and content tests

## License

The source code is available under the [MIT License](LICENSE). Included category artwork is provided for demonstration and is not covered by the MIT License.
