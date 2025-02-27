---
title: Docsifer
emoji: 👻 / 📚
colorFrom: green
colorTo: indigo
sdk: docker
app_file: app.py
pinned: false
---

# 📄 Docsifer: Efficient Data Conversion to Markdown

**Docsifer** is a powerful FastAPI + Gradio service for converting various data formats (PDF, PowerPoint, Word, Excel, Images, Audio, HTML, etc.) to Markdown. It leverages the [MarkItDown](https://github.com/microsoft/markitdown) library and can optionally use LLMs (via OpenAI) for richer extraction (OCR, speech-to-text, etc.).

## ✨ Key Features

- **Comprehensive Format Support**: 
  - **PDF**: Extracts text and structure effectively.
  - **PowerPoint**: Converts slides into Markdown-friendly content.
  - **Word**: Processes `.docx` files with precision.
  - **Excel**: Extracts tabular data as Markdown tables.
  - **Images**: Reads **EXIF metadata** and applies **OCR** for text extraction.
  - **Audio**: Retrieves **EXIF metadata** and performs **speech transcription**.
  - **HTML**: Transforms web pages into Markdown.
  - **Text-Based Formats**: Handles CSV, JSON, XML with ease.
  - **ZIP Files**: Iterates over contents for batch processing.
- **LLM Integration**: Leverages OpenAI's GPT-4 for enhanced extraction quality and contextual understanding.
- **Efficient and Fast**: Optimized for speed while maintaining high accuracy.
- **Easy Deployment**: Dockerized for hassle-free setup and scalability.
- **Interactive Playground**: Test conversion processes interactively using a **Gradio-powered interface**.
- **Usage Analytics**: Tracks token usage and access statistics via Upstash Redis.

## 🚀 Use Cases

- **Knowledge Indexing**: Convert various document formats into Markdown for indexing and search.
- **Text Analysis**: Prepare data for semantic analysis and NLP tasks.
- **Content Transformation**: Simplify content preparation for blogs, documentation, or databases.
- **Metadata Extraction**: Extract meaningful metadata from images and audio for categorization and tagging.

## 🛠️ Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/lh0x00/docsifer.git
cd docsifer
```

### 2. Build and Run with Docker
Make sure Docker is installed and running on your machine.
```bash
docker build -t lightweight-embeddings .
docker run -p 7860:7860 lightweight-embeddings
```

The API will now be accessible at `http://localhost:7860`.

## 📖 API Overview

### Endpoints

- **`/v1/convert`**: Convert a file to Markdown. Supports both file uploads and file path inputs. Accepts optional OpenAI parameters to enable LLM-based enhancements.
- **`/v1/stats`**: Retrieve usage statistics, including access counts and token usage.

### Interactive Docs

- Visit the [Swagger UI](http://localhost:7860/docs) for detailed, interactive documentation.
- Explore additional resources with [ReDoc](http://localhost:7860/redoc).

## 🔬 Playground

### Interactive Conversion

- Test file conversion directly in the browser using the **Gradio interface**.
- Simply visit `http://localhost:7860` after starting the server to access the playground.

### Features

- **File Upload**: Upload a file directly or provide a local file path.
- **OpenAI Integration**: Optionally provide OpenAI API details to enhance conversion with LLM capabilities.
- **Conversion Result**: View the resulting Markdown output instantly.
- **Usage Statistics**: Monitor access and token usage through the Gradio interface.

## 🌐 Resources

- **Documentation**: [Explore full documentation](https://lamhieu-docsifer.hf.space/docs)
- **Hugging Face Space**: [Try the live demo](https://huggingface.co/spaces/lh0x00/docsifer)
- **GitHub Repository**: [View source code](https://github.com/lh0x00/docsifer)

## 💡 Why Docsifer?

1. **Versatile and Comprehensive**: Handles a wide range of formats, making it a one-stop solution for content conversion.
2. **AI-Powered**: Uses OpenAI's GPT-4 to enhance extraction accuracy and adapt to complex data structures.
3. **User-Friendly**: Offers intuitive APIs and a built-in interactive interface for experimentation.
4. **Scalable and Efficient**: Optimized for performance with Docker support and asynchronous processing.
5. **Transparent Analytics**: Tracks usage metrics to help monitor and manage service consumption.

## 👥 Contributors

- **lamhieu / lh0x00** – Creator and Maintainer ([GitHub](https://github.com/lh0x00), [HuggingFace](https://huggingface.co/lamhieu))

Contributions are welcome! Check out the [contribution guidelines](https://github.com/lh0x00/docsifer/blob/main/CONTRIBUTING.md).

## 📜 License

This project is licensed under the **MIT License**. See the [LICENSE](https://github.com/lh0x00/docsifer/blob/main/LICENSE) file for details.

