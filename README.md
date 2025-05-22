# Gemini Lecture Assistant

A Python-based command-line tool to manage, index, and query lecture materials (videos, audio, PDFs, images, text) using Google's Gemini AI. This tool allows students or educators to quickly find information within a collection of learning resources through natural language queries.

## Features

*   **Multi-Modal Content Ingestion**: Add video, audio, PDF, image, and plain text files.
*   **Automatic Media Processing**:
    *   **Video**: Extracts audio (Opus format) and creates a downsampled video (1fps, 720p) for efficient analysis. Original videos are archived.
    *   **Audio**: Converts audio files to Opus format for consistency. Originals are archived.
*   **AI-Powered Indexing**: Uses Gemini to generate concise summaries for all ingested content, creating an searchable index.
*   **Natural Language Querying**: Ask questions in plain English about your lecture content.
*   **Intelligent Multi-Step Query Process**:
    1.  **Relevance Filtering**: Gemini first identifies potentially relevant files based on your query and the pre-generated summaries.
    2.  **Deep Analysis**: The content of the identified relevant files is then sent to Gemini along with your query for a more detailed answer.
    3.  **Answer Synthesis**: Gemini combines information from multiple sources (if applicable) to provide a comprehensive final answer.
*   **Metadata Management**: Stores file information, paths, types, and AI-generated summaries in a local JSON file (`lecture_data.json`).
*   **Error Handling & Retries**: Implements retries for Gemini API calls to handle transient network issues.

## Prerequisites

1.  **Python 3.7+**: Download from [python.org](https://www.python.org/downloads/).
2.  **FFmpeg**: Required for video and audio processing.
    *   Download from [ffmpeg.org](https://ffmpeg.org/download.html).
    *   Ensure `ffmpeg` is accessible in your system's PATH. Alternatively, if FFmpeg is installed but not in your PATH, you can specify its full path in the `FFMPEG_PATH` variable within the `gemini.py` script (see Configuration section).
3.  **Google AI Python SDK**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Google AI API Key**:
    *   Obtain an API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   Set it as an environment variable:
        ```bash
        export GOOGLE_API_KEY="YOUR_API_KEY"
        ```
        (On Windows, use `set GOOGLE_API_KEY=YOUR_API_KEY` in Command Prompt or `$env:GOOGLE_API_KEY="YOUR_API_KEY"` in PowerShell).

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/your-repo-name.git
    cd your-repo-name
    ```
2.  **Install Python dependencies:**
    It's recommended to use a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

## Configuration (Optional)

The script uses several constants at the top that you can modify:

*   `CONFIG_FILE = "lecture_data.json"`: Name of the metadata file.
*   `VIDEO_BASE_DIR = "lectures"`: Directory where processed files and archives are stored.
*   `API_RETRY_DELAY = 5`: Seconds to wait before retrying a failed API call.
*   `MAX_API_RETRIES = 3`: Maximum number of API call retries.
*   `GEMINI_MODEL_NAME`, `GEMINI_TEXT_MODEL_NAME`: Specific Gemini models to use. You might update these as new models are released.
    *   `FFMPEG_PATH = "ffmpeg"`: Path to the FFmpeg executable. If `ffmpeg` is not in your system's PATH, update this constant to the full path of the FFmpeg executable (e.g., `/usr/local/bin/ffmpeg` or `C:\ffmpeg\bin\ffmpeg.exe`).
*   `KNOWN_DOC_EXTENSIONS`: List of extensions automatically treated as documents (This list can be updated directly in the script if you need to support more document types that should be treated similarly to PDFs by default).

## Usage
### 1. Adding Content

Use the `add` command to ingest and index files. The script automatically creates a `lectures/` directory (and `lectures/Archive/`) to store processed and original media files.
In the examples below, replace placeholders like `course_notes.pdf` or `lecture_01.mp4` with the actual paths to your files.

*   **Add PDF files (auto-detected):**
    ```bash
    python gemini.py add course_notes.pdf research_paper.pdf
    ```

*   **Add video files:**
    ```bash
    python gemini.py add --videos lecture_01.mp4 "Chapter 2 Recording.mov"
    ```
    *This will extract audio, create a downsampled video in `lectures/`, archive the original in `lectures/Archive/`, and then index the processed files using Gemini.*

*   **Add audio files:**
    ```bash
    python gemini.py add --audio tutorial_audio.mp3 guest_lecture.wav
    ```
    *This will convert audio to Opus in `lectures/`, archive the original in `lectures/Archive/`, and index it.*

*   **Add image files:**
    ```bash
    python gemini.py add --images diagram.png flow_chart.jpeg
    ```
    *Images will be copied to `lectures/` and indexed.*

*   **Add text files:**
    ```bash
    python gemini.py add --text summary.txt code_examples.py
    ```
    *Text files will be copied to `lectures/` and indexed.*

*   **Add multiple types at once:**
    ```bash
    python gemini.py add syllabus.pdf --videos intro_video.mp4 --images slide1.png slide2.png
    ```

After adding, a summary will be generated by Gemini and stored in `lecture_data.json`. This might take some time, especially for longer videos.

### 2. Querying Content

Use the `query` command to ask questions about your indexed lectures.

```bash
python gemini.py query "What were the main topics discussed in the first video lecture?"
```

```bash
python gemini.py query "Explain the key concepts from the PDF about quantum computing."
```

```bash
python gemini.py query "When was the deadline for assignment 3 mentioned?"
```

The script will:
1.  Identify relevant lecture(s) based on summaries.
2.  Send the actual content of those lectures and your query to Gemini for a detailed answer.
3.  Synthesize and display a final answer.

## How It Works

1.  **Ingestion & Indexing (`add`):**
    *   When you add a file, it's assigned a unique UUID.
    *   **Media Preprocessing**:
        *   **Videos**: Are processed in two ways:
            *   Audio is extracted and converted to Opus format.
            *   A downsampled video stream is created (1 frame per second, 720p). This 1fps stream is then sped up 30x to create a compact MP4 file. This process significantly reduces the amount of data for analysis by Gemini, making it more efficient and helping to stay within token limits, while still providing a visual context when reviewing content.
        *   Audio files are converted to Opus.
        *   Original media files are moved to an `Archive` subfolder within `VIDEO_BASE_DIR`.
        *   PDFs, images, and text files are copied as-is to `VIDEO_BASE_DIR`.
    *   **Summary Generation**: The processed file(s) are uploaded to Gemini, which generates a textual summary.
    *   **Metadata Storage**: Information about the file (UUID, original filename, type, path to processed file(s), path to archive, and the Gemini-generated summary) is saved in `lecture_data.json`.

2.  **Querying (`query`):**
    *   **Step 1: Relevance Identification**:
        *   Your natural language query is sent to Gemini along with all the `index_summary` fields from `lecture_data.json`.
        *   Gemini returns a list of numerical UUIDs (e.g., 1, 5, 12) it deems most relevant to your query based on these summaries.
    *   **Step 2: Content-Specific Answering**:
        *   For each relevant UUID, the script retrieves the actual processed file(s) (e.g., the Opus audio and downsampled MP4 for a video).
        *   These files are uploaded to Gemini along with your original query.
        *   Gemini analyzes this specific content to generate an answer related to *that particular lecture/document*.
    *   **Step 3: Final Answer Synthesis**:
        *   All the individual answers from Step 2 are compiled.
        *   This compilation is sent to Gemini one last time, with instructions to synthesize a single, comprehensive final answer based on the provided individual answers.

## File Structure

```
your-repo-name/
├── gemini.py  # Or your script name
├── lecture_data.json     # Stores metadata and summaries (created automatically)
├── lectures/             # Stores processed files (created automatically)
│   ├── 1.lecture_01.opus
│   ├── 1.lecture_01.mp4
│   ├── 2.tutorial_audio.opus
│   ├── 3.diagram.png
│   ├── 4.summary.txt
│   ├── 5.course_notes.pdf
│   └── Archive/          # Stores original media files (created automatically)
│       ├── lecture_01.mp4
│       └── tutorial_audio.mp3
└── README.md
```

## Limitations & Future Considerations

*   **API Costs**: Frequent indexing or querying of large files can incur costs with the Google AI API. Be mindful of your usage.
*   **API Rate Limits/Quotas**: The script includes retries, but persistent rate limiting might require adjusting usage patterns or requesting quota increases from Google.
*   **Token Limits**: Very long videos or documents might exceed Gemini's context window for summarization or querying. The current video processing (1fps) helps mitigate this for video.
*   **Processing Time**: Indexing large media files can be time-consuming due to uploading and AI processing.
*   **No Deletion/Update Feature**: Currently, there's no built-in command to remove or re-index specific entries. This would require manual editing of `lecture_data.json` and file system cleanup, or an extension to the script.
*   **FFmpeg Dependency**: Relies on an external FFmpeg installation.

## Troubleshooting

### FFmpeg not found / `ffmpeg` command not recognized
*   **Solution:**
    *   Ensure FFmpeg is correctly installed on your system. You can download it from [ffmpeg.org](https://ffmpeg.org/download.html).
    *   Verify that the directory containing `ffmpeg` (and `ffprobe`) is included in your system's PATH environment variable.
    *   If FFmpeg is installed but not in your PATH, you can set the `FFMPEG_PATH` constant in the `gemini.py` script to the full path of the `ffmpeg` executable (e.g., `/usr/local/bin/ffmpeg` or `C:\ffmpeg\bin\ffmpeg.exe`).

### Google AI API Key not set or invalid / Authentication errors
*   **Solution:**
    *   Make sure you have obtained a Google AI API Key from [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   Confirm that the `GOOGLE_API_KEY` environment variable is correctly set in your terminal session or system environment variables. For example:
        *   Linux/macOS: `export GOOGLE_API_KEY="YOUR_API_KEY"`
        *   Windows (Command Prompt): `set GOOGLE_API_KEY=YOUR_API_KEY`
        *   Windows (PowerShell): `$env:GOOGLE_API_KEY="YOUR_API_KEY"`
    *   Ensure there are no typos in the API key and that it has the necessary permissions/is enabled.

### `pip install -r requirements.txt` fails
*   **Solution:**
    *   Ensure you have Python 3.7+ installed and that `pip` is up to date (`python -m pip install --upgrade pip`).
    *   If you are using a virtual environment, make sure it is activated.
    *   Check your internet connection, as pip needs to download packages.
    *   If you encounter errors related to specific packages, try searching for solutions online for that particular package error.

## Contributing

Contributions are welcome! If you have suggestions for improvements, new features, or find any bugs, please feel free to:

1.  **Report Bugs:** Open an issue in the GitHub repository, providing as much detail as possible.
2.  **Suggest Enhancements:** Open an issue to discuss new features or improvements.
3.  **Submit Pull Requests:**
    *   Fork the repository.
    *   Create a new branch for your feature or bug fix.
    *   Make your changes.
    *   Ensure your code follows the project's style (if any defined) and is well-commented.
    *   Write or update tests if applicable.
    *   Submit a pull request with a clear description of your changes.

## License

This project is licensed under the MIT License. See the `LICENSE` file for more details.

*(Note: If a `LICENSE` file does not exist, please choose an appropriate open-source license and add it to the repository. For example, you can create a file named `LICENSE` and add the MIT License text to it.)*