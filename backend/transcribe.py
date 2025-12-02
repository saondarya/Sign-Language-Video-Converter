import whisper

# Load Whisper model
model = whisper.load_model("base")

# Path to your video file
video_file = "theja.mp4"  # Update this if needed

# Transcribe the audio
print("Transcribing...")
result = model.transcribe(video_file)

# Print full transcript
print("\n--- Transcript ---\n")
print(result)

# Ask user if they want to save the transcript
save_option = input("\nDo you want to save the transcript to a file? (yes/no): ").strip().lower()

if save_option in ["yes", "y"]:
    with open("transcript.txt", "w", encoding="utf-8") as f:
        f.write(result["text"])
    print("✅ Transcript saved to transcript.txt")
else:
    print("❌ Transcript not saved.")
