import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import google.genai.types as types
from google import genai

# --- Configuration ---
CONFIG_FILE = "lecture_data.json"
VIDEO_BASE_DIR = "lectures"
API_RETRY_DELAY = 5  # Seconds to wait before retrying API call on failure
MAX_API_RETRIES = 3

# --- Model Selection ---
GEMINI_MODEL_NAME = "models/gemini-2.5-flash-preview-04-17"
GEMINI_TEXT_MODEL_NAME = "models/gemini-2.5-flash-preview-04-17"

# --- FFmpeg Configuration ---
FFMPEG_PATH = "ffmpeg"

KNOWN_DOC_EXTENSIONS = [
    ".pdf",
]

FILE_TYPES = [
    "Video",
    "Audio",
    "Image",
    "Text",
    "PDF",
]


def load_metadata(
    filename=CONFIG_FILE,
) -> dict:
    """
    Loads metadata from the JSON file.
    The formal will look something like this:
    ```json
    {
      "UUID": {
        "1": {
          "Filename": "String",         # This will be the name of the file, no real use
          "Type": "String",             # This will be the type of file,
          "Path": [                     # Path to the file(s)
            "String:Path",
            "String:Path"
          ],
          "Archive": "String:Path"      # Some files need to be encoded, this will the original file
          "index_summary" : "String"    # This will be the summary of the file
        }
      }
    }
    ```
    """
    if not Path(filename).exists():
        return {"UUID": {}}
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            if "UUID" not in data:
                data["UUID"] = {}
            return data
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filename}. Starting fresh.")
        return {"UUID": {}}


def save_metadata(
    data: dict,
    filename=CONFIG_FILE,
) -> None:
    """Saves metadata to the JSON file."""
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


def get_structured_uuids_response(
    user_input_text: str,
    data: dict,
    model: str = GEMINI_TEXT_MODEL_NAME,
) -> dict | None:
    """
    Generates a structured response from the Gemini API based on user input.
    Returns a dictionary with a list of UUIDs or None on failure.

    Args:
        user_input_text (str): The user's query or input text.
        data (dict): The metadata containing UUIDs and their summaries.
        model (str): The model to use for generation. Default is GEMINI_TEXT_MODEL_NAME.
    """
    prompt = (
        "You are an AI assistant helping a student find information in lecture recordings.\n"
        "You will look at all of the summaries of all of the documents and return a list of UUIDs for the documents"
        "that you think are relevant to the user's query.\n"
        "You CAN return multiple UUIDs if you think multiple documents are relevant.\n"
        "Here is the User's query:\n"
    )
    prompt = (
        prompt
        + user_input_text
        + "\n\n"
        + "Here is the list of UUIDs and their summaries:\n"
    )

    prompt = prompt + json.dumps(
        data,
        indent=0,
    )

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=prompt,
                ),
            ],
        ),
    ]

    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "UUIDs": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.INTEGER,
                    ),
                ),
            },
        ),
    )
    response = None
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generation_config,
        )

        if response.text:
            parsed_json = json.loads(response.text)
            return parsed_json
        else:
            print("Warning: Received empty text in response.")
            return None

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from model response: {e}")
        print("Raw response:", response)
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def safe_generate_content(
    model: str, prompt: list, retries=MAX_API_RETRIES
) -> str | None:
    """
    Safely call the Gemini API with retries.

    args:
        model (str): The model to use for generation.
        prompt (list): The prompt to send to the model.
        retries (int): Number of retries on failure.
    """
    for attempt in range(retries):
        try:
            generate_content_config = types.GenerateContentConfig(
                response_mime_type="text/plain",
            )
            client = genai.Client()
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=generate_content_config,
            )
            if not response:
                print("Warning: Received empty response from API.")
                return None
            if hasattr(response, "text"):
                return response.text
            else:
                raise Exception("Response does not have 'text' attribute.")
        except Exception as e:
            print(f"Error calling Gemini API (Attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                print(f"Retrying in {API_RETRY_DELAY} seconds...")
                time.sleep(API_RETRY_DELAY)
            else:
                print("Max retries reached. API call failed.")
                error_details = getattr(e, "message", str(e))
                return (
                    f"Error: API call failed after {retries} retries: {error_details}"
                )
    return None


def extract_from_video(
    video_path: Path,
    output_dir: Path,
) -> list[Path] | None:
    """
    Extracts the audio and video from a given video file using FFmpeg.
    We do this separately so that we can reduce the amount of video data we send to Gemini.
    We will only be taking 1 frame per second, at 720p resolution.
    Returns the path to the extracted audio file or None on failure.
    """
    no = str(len(load_metadata()["UUID"]) + 1)
    audio_filename = no + "." + video_path.stem + ".opus"
    video_filename = no + "." + video_path.stem + ".mp4"
    audio_output_path = output_dir / audio_filename
    video_output_path = output_dir / video_filename
    print(f"   Extracting audio to: {audio_output_path}")

    command = [
        FFMPEG_PATH,
        "-i",
        str(video_path),  # Input video file
        "-vn",  # No video output
        "-c:a",
        "libopus",  # Audio codec: Opus
        "-b:a",
        "64k",  # Audio bitrate: 64kbps, gemini can only handle 16kbps. Extra bitrate for the future
        "-y",  # Overwrite output file if it exists
        str(audio_output_path),  # Output audio file
    ]

    command1 = [
        FFMPEG_PATH,
        "-i",
        str(video_path),  # Input video file
        "-vf",
        "fps=1,scale=-1:720,setpts=PTS/30",  # Extract 1 frame per second of input,
        # then scale it,
        # then speed up the resulting stream of frames by 30x
        "-r",
        "30",  # Set output frame rate to 30 fps
        "-an",  # No audio in the output
        "-y",  # Overwrite output file if it exists
        str(video_output_path),  # Output file
    ]

    try:
        if not shutil.which(FFMPEG_PATH):
            print(
                f"Error: '{FFMPEG_PATH}' command not found. Please install FFmpeg and ensure it's in your PATH."
            )
            return None

        print(f"   Running FFmpeg command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=False, text=True, check=True)
        result1 = subprocess.run(command1, capture_output=False, text=True, check=True)
        print("FFmpeg Errors: ")
        print(result.stderr)
        print(result1.stderr)
        return [video_output_path, audio_output_path]
    except FileNotFoundError:
        print(
            f"Error: '{FFMPEG_PATH}' command not found. Please install FFmpeg and ensure it's in your PATH."
        )
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error during FFmpeg execution (Return Code: {e.returncode}):")
        print(f"   Command: {' '.join(e.cmd)}")
        print(f"   Stderr: {e.stderr}")
        print(f"   Stdout: {e.stdout}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during audio extraction: {e}")
        return None


def extract_from_audio(
    audio_path: Path,
    output_dir: Path,
) -> list[Path] | None:
    """
    Converts an audio file to Opus format using FFmpeg.
    Returns the path to the converted audio file or None on failure.
    """
    audio_filename = audio_path.stem + ".opus"
    audio_output_path = output_dir / audio_filename
    print(f"   Converting audio to: {audio_output_path}")

    command = [
        FFMPEG_PATH,
        "-i",
        str(audio_path),  # Input audio file
        "-c:a",
        "libopus",  # Audio codec: Opus
        "-b:a",
        "192k",  # Audio bitrate: 192kbps
        "-y",  # Overwrite output file if it exists
        str(audio_output_path),  # Output audio file
    ]

    try:
        if not shutil.which(FFMPEG_PATH):
            print(
                f"Error: '{FFMPEG_PATH}' command not found. Please install FFmpeg and ensure it's in your PATH."
            )
            return None

        print(f"   Running FFmpeg command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=False, text=True, check=True)
        if result.stderr and not result.stderr.strip().endswith("size="):
            print(f"FFmpeg messages: {result.stderr}")
        return [audio_output_path]
    except FileNotFoundError:
        print(
            f"Error: '{FFMPEG_PATH}' command not found. Please install FFmpeg and ensure it's in your PATH."
        )
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error during FFmpeg execution (Return Code: {e.returncode}):")
        print(f"   Command: {' '.join(e.cmd)}")
        print(f"   Stderr: {e.stderr}")
        print(f"   Stdout: {e.stdout}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during audio conversion: {e}")
        return None


def index_content(
    path: list[Path],
) -> str | None:
    """
    Uses Gemini to generate a summary/index for the list of files passed in.
    It will pass all the files to the API in one call and return a string if successful.
    """
    client = genai.Client()
    print(f"Indexing File: {path} (this may take a while)...")
    print(f"Uploading file: {path}...")
    temp_list = []
    for file in path:
        if not file.exists():
            print(f"Error: File {file} does not exist. Continuing with other files.")
        temp_list.append(file)
    path = temp_list
    del temp_list
    uploaded_files = []
    for file in path:
        print(f"Uploading file: {file}...")
        uploaded_file = client.files.upload(file=file)
        uploaded_files.append(uploaded_file)
        print("The time rn:", time.time_ns())

    print("Files uploaded. Generating index...")
    prompt = (
        "Analyze this lecture and provide a concise summary "
        "including the main topics discussed, key concepts, definitions, "
        "and any specific examples mentioned. Format the output clearly."
    )

    # Make the API call with the audio file object
    response_text = safe_generate_content(GEMINI_MODEL_NAME, [prompt] + uploaded_files)
    if response_text:
        return response_text
    else:
        print(f"Indexing failed. API Response: {response_text}")
        return None


# --- Query Functionality ---
def query_lectures(query: str):
    """Handles the natural language query using the multi-step Gemini process with audio."""
    metadata = load_metadata()
    data = metadata["UUID"]
    if not data:
        print("No lectures have been added yet.")
        return
    videos_data = {}
    for key, value in data.items():
        videos_data[key] = value["index_summary"]
    print("Step 1: Identifying relevant lectures based on summaries...")

    summaries_context = json.dumps(videos_data, indent=0)

    if not summaries_context.strip():
        print("No valid index summaries found in metadata. Cannot determine relevance.")
        return

    relevance_prompt = (
        f"You are an AI assistant helping a student find information in lecture recordings.\n"
        f"Based *only* on the following lecture summaries (derived from audio), identify which lecture identifiers (e.g., 'day1', 'day5') "
        f"are most likely to contain information relevant to the user's query.\n"
        f"List *only* the identifiers, separated by commas (e.g., day1, day3, day7).\n\n"
        f'User Query: "{query}"\n\n'
        f"Available Lecture Summaries:\n{summaries_context}\n\n"
        f"Relevant Lecture Identifiers:"
    )

    relevant_ids = get_structured_uuids_response(
        query,
        videos_data,
    )

    if not relevant_ids:
        print(f"Error during relevance check: {relevant_ids}")
        return

    relevant_ids = relevant_ids["UUIDs"]

    if not relevant_ids:
        print(
            "Based on the summaries, no specific lectures seem relevant to your query."
        )
        return

    print(f"Step 2: Querying relevant lecture audio: {relevant_ids}")

    individual_answers = {}
    client = genai.Client()
    for UUID in relevant_ids:
        lecture_info = metadata["UUID"][str(UUID)]
        files = lecture_info["Path"]
        print(f"Querying relevant lecture audio: {', '.join(files)}")
        for i in files:
            if not Path(i).exists():
                print(f"Error: File {i} does not exist. Continuing with other files.")
        files = [Path(i) for i in files if Path(i).exists()]

        query_to_send = ["Using the data provided answer the query\n", query]
        for i in files:
            temp = client.files.upload(file=i)
            query_to_send.append(temp)

        ans = safe_generate_content(GEMINI_MODEL_NAME, query_to_send)
        individual_answers[UUID] = ans

    print("Step 3: Synthesizing the final answer...")

    synthesis_context = "\n\n".join(
        [
            f"Answer from File {uuid}:\n{ans}"
            for uuid, ans in individual_answers.items()
            if ans and "Error:" not in ans
        ]
    ).strip()

    if not synthesis_context.strip():
        print(
            "No valid answers were successfully retrieved from the relevant data.\n",
            "Data generated\n",
            synthesis_context,
        )
        return

    final_prompt = (
        f"You are an AI assistant synthesizing information from different lecture audio segments to answer a student's query.\n"
        f'The student asked: "{query}"\n\n'
        f"Based *only* on the following answers derived directly from the relevant lecture audio recordings, "
        f"provide a single, comprehensive, and well-structured final answer. "
        f"If the individual answers conflict, are insufficient, or indicate errors, acknowledge that.\n\n"
        f"Individual Answers:\n{synthesis_context}\n\n"
        f"Final Synthesized Answer:"
    )

    final_answer = safe_generate_content(GEMINI_TEXT_MODEL_NAME, [final_prompt])

    if final_answer and "Error:" not in final_answer:
        print("=" * 80)
        print("\n--- Final Answer ---")
        print(final_answer)
        print("=" * 80)
    else:
        print(f"Failed to synthesize a final answer. API response: {final_answer}")
        print("\nIndividual Answers Used:")
        print(synthesis_context)  # Show context that led to synthesis failure


def create_parser():
    """Creates and configures the argument parser."""
    parser = argparse.ArgumentParser(
        description="Manage and query lecture content (audio, video, images, text) via Gemini."
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    # --- ADD command ---
    add_parser = subparsers.add_parser(
        "add",
        help="Add various content files to the system. Document types (pdf, docx, pptx) are auto-detected.",
        description=(
            "Add files to the lecture database. "
            "Files with extensions .pdf, .docx, .pptx are automatically categorized as documents. "
            "Use flags for other types like videos, images, and specific text files."
        ),
    )
    add_parser.add_argument(
        "document_files",
        metavar="DOC_PPT_PDF_FILE",
        nargs="*",
        default=[],
        help="Path to document files (e.g., a.pdf). These are auto-detected.",
    )
    add_parser.add_argument(
        "--videos",
        metavar="VIDEO_FILE",
        nargs="+",
        default=[],
        help="Path to video files (e.g., vidFile1.mp4, vidFile2.mov).",
    )
    add_parser.add_argument(
        "--audio",
        metavar="AUDIO_FILE",
        nargs="+",
        default=[],
        help="Path to audio files (e.g., audioFile1.mp3, audioFile2.wav).",
    )
    add_parser.add_argument(
        "--images",
        metavar="IMAGE_FILE",
        nargs="+",
        default=[],
        help="Path to image files (e.g., ImageFile1.png, ImageFile2.jpeg).",
    )
    add_parser.add_argument(
        "--text",
        metavar="TEXT_FILE",
        nargs="+",
        default=[],
        help="Path to text or code files (e.g., text1.txt, code.java).",
    )

    # --- QUERY command ---
    query_parser = subparsers.add_parser(
        "query", help="Query the lecture content using natural language."
    )
    query_parser.add_argument(
        "query_text",
        metavar="QUERY_TEXT",
        nargs="+",
        help="Natural language question about the lectures.",
    )

    return parser, add_parser, query_parser


def handle_add_command(args, add_parser_obj):
    """Handles the 'add' command."""
    print("--- Processing 'add' command ---")

    all_document_files = []
    all_video_files = args.videos
    all_audio_files = args.audio
    all_image_files = args.images
    all_text_files = args.text
    unrecognized_files = []

    # Process auto-detected document files from positional arguments
    for file_path in args.document_files:
        _, ext = os.path.splitext(file_path.lower())
        if ext in KNOWN_DOC_EXTENSIONS:
            all_document_files.append(file_path)
        else:
            print(f"Warning: Unrecognized extension for positional file '{file_path}'.")
            unrecognized_files.append(file_path)

    print(f"Document files to add: {all_document_files}")
    print(f"Video files to add: {all_video_files}")
    print(f"Audio files to add: {all_audio_files}")
    print(f"Image files to add: {all_image_files}")
    print(f"Text files to add: {all_text_files}")
    if unrecognized_files:
        print(f"Unrecognized positional files: {unrecognized_files}")
        print(
            "Consider using --videos, --audio, --images, or --text for these, or add their extensions if they are documents."
        )

    # are there any files to add?
    if not any(
        [
            all_document_files,
            all_video_files,
            all_audio_files,
            all_image_files,
            all_text_files,
            unrecognized_files,
        ]
    ):
        print("No files specified to add.")
        add_parser_obj.print_help()
    return (
        all_document_files,
        all_video_files,
        all_audio_files,
        all_image_files,
        all_text_files,
    )


def handle_query_command(args):
    """Handles the 'query' command."""
    print("--- Processing 'query' command ---")
    full_query = " ".join(args.query_text)
    print(f"Querying with: '{full_query}'")
    query_lectures(full_query)


def add_to_index(
    file_paths: list[Path],
    file_type: str,
):
    """
    This assumes that the file(s) need to be added to the index, so they are not in the lecture folder.
    It will add the file(s) to the json file.
    """
    if not file_paths:
        print("No files to add to index.")
        return
    metadata = load_metadata()
    next_uuid = len(metadata["UUID"]) + 1
    for i in file_paths:
        if not i.exists():
            print(f"Error: File {i} does not exist. Continuing with other files.")
            continue
    paths = []
    archive = None
    os.makedirs(Path(VIDEO_BASE_DIR) / "Archive", exist_ok=True)
    if file_type == FILE_TYPES[0]:  # Video
        paths = extract_from_video(file_paths[0], Path(VIDEO_BASE_DIR))
        archive = Path(VIDEO_BASE_DIR) / "Archive"
        archive = shutil.copy(file_paths[0], archive)
    elif file_type == FILE_TYPES[1]:  # Audio
        paths = extract_from_audio(file_paths[0], Path(VIDEO_BASE_DIR))
        archive = Path(VIDEO_BASE_DIR) / "Archive"
        archive = shutil.copy(file_paths[0], archive)
    elif file_type == FILE_TYPES[2]:  # Image
        paths = [Path(shutil.copy(file_paths[0], Path(VIDEO_BASE_DIR)))]
    elif file_type == FILE_TYPES[3]:  # Text
        paths = [Path(shutil.copy(file_paths[0], Path(VIDEO_BASE_DIR)))]
    elif file_type == FILE_TYPES[4]:  # PDF
        paths = [Path(shutil.copy(file_paths[0], Path(VIDEO_BASE_DIR)))]
    file_paths = paths.copy()
    for i in file_paths:
        if not i.exists():
            print(f"Error: File {i} does not exist. Continuing with other files.")
            continue
    paths = [str(i) for i in file_paths if i.exists()]
    data = {
        "Path": paths,
        "Filename": file_paths[0].name,
        "Type": file_type,
        "Archive": "",
        "index_summary": "",
    }
    if archive:
        data["Archive"] = str(archive)
    summary = index_content(file_paths)
    if summary:
        print("Summary: ", summary)
        data["index_summary"] = summary
    else:
        print("Error: Summary not generated.")
        data["index_summary"] = "Error: Summary not generated."
    metadata["UUID"][next_uuid] = data
    save_metadata(metadata)


def main():
    if not shutil.which(FFMPEG_PATH):
        print("=" * 80)
        print(f"ERROR: FFmpeg command ('{FFMPEG_PATH}') not found in system PATH.")
        print("Please install FFmpeg from https://ffmpeg.org/download.html")
        print(
            "and ensure the installation location is added to your PATH environment variable."
        )
        print("=" * 80)
        sys.exit(1)

    parser, add_parser_obj, query_parser_obj = create_parser()
    args = parser.parse_args()
    if args.command == "add":
        pdf, video, audio, image, text = handle_add_command(args, add_parser_obj)
        for i in pdf:
            add_to_index([Path(i)], FILE_TYPES[4])  # PDF
        for i in video:
            add_to_index([Path(i)], FILE_TYPES[0])
        for i in audio:
            add_to_index([Path(i)], FILE_TYPES[1])  # Audio
        for i in image:
            add_to_index([Path(i)], FILE_TYPES[2])
        for i in text:
            add_to_index([Path(i)], FILE_TYPES[3])
    elif args.command == "query":
        handle_query_command(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
