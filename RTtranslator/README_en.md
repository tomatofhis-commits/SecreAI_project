# Real-Time Translator

A powerful, entirely local real-time screen translation tool designed for games and applications. It uses advanced OCR technology and local LLMs to seamlessly overlay translations onto your screen.

[日本語版のREADMEはこちら (Japanese README)](README.md)

## Key Features

- **Advanced OCR Pipeline**: Choose from three optimized processing plans:
    - **Plan 1 (WinRT Only)**: Uses a 2-pass logic to improve accuracy while maintaining high speed.
    - **Plan 2 (Hybrid)**: The standard mode where WinRT defines regions and PaddleOCR performs detailed reading and line merging.
    - **Plan 4 (Dual-Scout Hybrid)**: The highest precision mode, scouting regions with both engines before final PaddleOCR refinement.
- **Local LLM Translation**: Privacy-first translations using [Ollama](https://ollama.com/) (e.g., `translategemma:4b`). No API keys or external data transmission required.
- **Dynamic UI Optimization**: New iterative algorithm automatically finds the largest possible font size that fits perfectly within the original text area.
- **Intelligent Cache Management**: Resets cache on startup and auto-cleans noise when resuming. Features Fuzzy Matching (85%+) to handle OCR inconsistencies instantly.
- **Flicker-Free & Guardrails**: Integrated `fastText` validation and auto-retry logic for translation failures. Filters out UI symbols and noise for a rock-solid overlay.

## Prerequisites

- **OS**: Windows 10 or Windows 11 (required for WinRT OCR)
- **Python**: Python 3.10 or higher
- **Ollama**: Must be installed and running locally. Pull the required model by running:
  ```bash
  ollama run translategemma:4b
  ```

## Installation & Setup

1. **Clone or Download the Repository:**
   ```bash
   git clone <repository_url>
   cd Real_Time_Translate
   ```

2. **Install Dependencies:**
   It is highly recommended to use a virtual environment.
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Settings (Optional):**
   Modify `config.json` to change the target window title, target language, translation model, or overlay UI settings.
   ```json
   {
     "window_title": "Target Application Window Title",
     "target_language": "ja",
     "translation_model": "translategemma:4b"
   }
   ```

4. **Run the Application:**
   ```bash
   python main.py
   ```
   The transparent overlay will automatically attach to the configured window and begin translating!

## How It Works

1. **Screen Capture**: Periodically captures the target window.
2. **OCR Extraction**: Dynamically selects between WinRT OCR (2-Pass) and PaddleOCR depending on your chosen plan, ensuring optimal line merging.
3. **Filtering & Validation**: `fastText` detects translatable text while filtering out noise. An auto-retry mechanism ensures high-quality translation even if the first attempt fails.
4. **Translation Queue**: Only unknown texts (checked against fuzzy-matched cache) are sent to Ollama. Cache is reset on startup for a fresh environment.
5. **Overlay Rendering**: Uses an iterative font-sizing algorithm to maximize readability while strictly staying within the original text boundaries.

## How to Display in OBS Studio

To capture the translation overlay for streaming or recording in OBS Studio, use the "Browser Source" feature:

1. Add a **"Browser"** source in your OBS scene.
2. Set the "URL" field to `http://localhost:5001/overlay`.
3. Set the "Width" and "Height" to match your target game or monitor resolution (e.g., 1920 and 1080).
4. (Optional) Clear the "Custom CSS" field if necessary.
5. In your sources list, arrange this Browser source so it sits directly above your game capture source.

## License
This project is open-source. Please see the LICENSE file for details.
