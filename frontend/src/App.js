import React, { useState, useEffect, useRef } from "react";
import "./App.css";
import axios from "axios";
import MedicationIcon from "./components/MedicationIcon";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function App() {
  const [medications, setMedications] = useState([]);
  const [inputText, setInputText] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [processedResult, setProcessedResult] = useState(null);
  const [activeTab, setActiveTab] = useState("input");
  const [previewImage, setPreviewImage] = useState(null);
  
  // Voice recording states
  const [isRecording, setIsRecording] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [speechRecognition, setSpeechRecognition] = useState(null);
  const [audioSupported, setAudioSupported] = useState(false);

  useEffect(() => {
    fetchMedications();
    initializeSpeechRecognition();
  }, []);

  const initializeSpeechRecognition = () => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';
      
      recognition.onstart = () => {
        setIsRecording(true);
      };
      
      recognition.onresult = (event) => {
        let finalTranscript = '';
        let interimTranscript = '';
        
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interimTranscript += transcript;
          }
        }
        
        setVoiceTranscript(finalTranscript + interimTranscript);
      };
      
      recognition.onend = () => {
        setIsRecording(false);
      };
      
      recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        setIsRecording(false);
      };
      
      setSpeechRecognition(recognition);
      setAudioSupported(true);
    } else {
      setAudioSupported(false);
    }
  };

  const startRecording = () => {
    if (speechRecognition && !isRecording) {
      setVoiceTranscript("");
      speechRecognition.start();
    }
  };

  const stopRecording = () => {
    if (speechRecognition && isRecording) {
      speechRecognition.stop();
    }
  };

  const fetchMedications = async () => {
    try {
      const response = await axios.get(`${API}/medications`);
      setMedications(response.data);
    } catch (error) {
      console.error("Error fetching medications:", error);
    }
  };

  const convertFileToBase64 = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        // Remove the data:image/jpeg;base64, prefix
        const base64String = reader.result.split(',')[1];
        resolve(base64String);
      };
      reader.onerror = error => reject(error);
    });
  };

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      setSelectedFile(file);
      // Create preview
      const reader = new FileReader();
      reader.onload = (e) => setPreviewImage(e.target.result);
      reader.readAsDataURL(file);
    }
  };

  const processPrescription = async () => {
    if (!inputText && !selectedFile && !voiceTranscript) {
      alert("Please provide text, upload an image, or record voice input");
      return;
    }

    setProcessing(true);
    try {
      let requestData = {};
      
      if (selectedFile) {
        const base64Image = await convertFileToBase64(selectedFile);
        requestData.image_base64 = base64Image;
      }
      
      if (inputText) {
        requestData.text = inputText;
      }

      if (voiceTranscript) {
        requestData.voice_transcription = voiceTranscript;
      }

      const response = await axios.post(`${API}/process-prescription`, requestData);
      setProcessedResult(response.data);
      setActiveTab("results");
      fetchMedications(); // Refresh the medications list
    } catch (error) {
      console.error("Error processing prescription:", error);
      alert("Error processing prescription. Please try again.");
    } finally {
      setProcessing(false);
    }
  };

  const deleteMedication = async (medicationId) => {
    try {
      await axios.delete(`${API}/medications/${medicationId}`);
      fetchMedications();
    } catch (error) {
      console.error("Error deleting medication:", error);
    }
  };

  const clearInput = () => {
    setInputText("");
    setSelectedFile(null);
    setPreviewImage(null);
    setProcessedResult(null);
    setVoiceTranscript("");
  };

  const formatTime = (timeStr) => {
    if (!timeStr) return "";
    const [hours, minutes] = timeStr.split(':');
    const hour = parseInt(hours);
    const period = hour >= 12 ? 'PM' : 'AM';
    const displayHour = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
    return `${displayHour}:${minutes} ${period}`;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-800 mb-2">
            🏥 Advanced Prescription Processor
          </h1>
          <p className="text-gray-600">
            Upload images, enter text, or speak your prescription details for AI-powered processing
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="flex justify-center mb-8">
          <div className="bg-white rounded-lg p-1 shadow-md">
            <button
              onClick={() => setActiveTab("input")}
              className={`px-6 py-2 rounded-md font-medium transition-all ${
                activeTab === "input"
                  ? "bg-blue-500 text-white shadow-md"
                  : "text-gray-600 hover:text-blue-500"
              }`}
            >
              📋 Process Prescription
            </button>
            <button
              onClick={() => setActiveTab("medications")}
              className={`px-6 py-2 rounded-md font-medium transition-all ${
                activeTab === "medications"
                  ? "bg-blue-500 text-white shadow-md"
                  : "text-gray-600 hover:text-blue-500"
              }`}
            >
              💊 My Medications ({medications.length})
            </button>
            {processedResult && (
              <button
                onClick={() => setActiveTab("results")}
                className={`px-6 py-2 rounded-md font-medium transition-all ${
                  activeTab === "results"
                    ? "bg-blue-500 text-white shadow-md"
                    : "text-gray-600 hover:text-blue-500"
                }`}
              >
                ✅ Latest Results
              </button>
            )}
          </div>
        </div>

        {/* Tab Content */}
        {activeTab === "input" && (
          <div className="max-w-4xl mx-auto">
            <div className="bg-white rounded-xl shadow-lg p-8">
              <h2 className="text-2xl font-bold text-gray-800 mb-6 text-center">
                📄 Multiple Input Methods Available
              </h2>
              
              {/* Image Upload Section */}
              <div className="mb-8">
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  📷 Upload Prescription Image (Enhanced OCR)
                </label>
                <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 transition-colors">
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleFileSelect}
                    className="hidden"
                    id="file-input"
                  />
                  <label htmlFor="file-input" className="cursor-pointer">
                    {previewImage ? (
                      <div>
                        <img
                          src={previewImage}
                          alt="Preview"
                          className="max-w-xs max-h-48 mx-auto rounded-lg shadow-md mb-3"
                        />
                        <p className="text-sm text-gray-500">Click to change image</p>
                      </div>
                    ) : (
                      <div>
                        <div className="text-6xl mb-3">📷</div>
                        <p className="text-gray-600 mb-2">Click to upload prescription image</p>
                        <p className="text-sm text-gray-500">AI will read even distorted handwriting</p>
                      </div>
                    )}
                  </label>
                </div>
              </div>

              {/* Voice Input Section */}
              {audioSupported && (
                <div className="mb-8">
                  <label className="block text-sm font-medium text-gray-700 mb-3">
                    🎤 Voice Input (Speak Your Prescription)
                  </label>
                  <div className="border border-gray-300 rounded-lg p-4">
                    <div className="flex items-center gap-4 mb-4">
                      <button
                        onClick={startRecording}
                        disabled={isRecording || processing}
                        className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                          isRecording
                            ? "bg-red-500 text-white"
                            : "bg-green-500 hover:bg-green-600 text-white disabled:bg-gray-400"
                        }`}
                      >
                        {isRecording ? (
                          <>
                            🔴 Recording...
                          </>
                        ) : (
                          <>
                            🎤 Start Recording
                          </>
                        )}
                      </button>
                      
                      {isRecording && (
                        <button
                          onClick={stopRecording}
                          className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium"
                        >
                          ⏹️ Stop
                        </button>
                      )}
                      
                      {voiceTranscript && (
                        <button
                          onClick={() => setVoiceTranscript("")}
                          className="px-3 py-2 bg-gray-500 hover:bg-gray-600 text-white rounded-lg text-sm"
                        >
                          🗑️ Clear
                        </button>
                      )}
                    </div>
                    
                    {voiceTranscript && (
                      <div className="bg-gray-50 p-3 rounded-lg">
                        <p className="text-sm font-medium text-gray-700 mb-1">Transcribed:</p>
                        <p className="text-gray-800">{voiceTranscript}</p>
                      </div>
                    )}
                    
                    <p className="text-xs text-gray-500 mt-2">
                      Example: "I need to take Dolo 650 one tablet three times daily for five days"
                    </p>
                  </div>
                </div>
              )}

              {/* Divider */}
              <div className="flex items-center my-8">
                <div className="flex-1 border-t border-gray-300"></div>
                <span className="px-4 text-gray-500 font-medium">OR</span>
                <div className="flex-1 border-t border-gray-300"></div>
              </div>

              {/* Text Input Section */}
              <div className="mb-8">
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  ✏️ Enter Prescription Text (Supports Medical Abbreviations)
                </label>
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  className="w-full h-32 p-4 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Enter prescription details like:&#10;Tab Dolo 650 OD x 5d&#10;Cap Amoxil 500 BD x 7d&#10;Syr Cetirizine 5ml TDS x 3d&#10;&#10;Supports medical abbreviations: OD, BD, TDS, QDS, etc."
                />
                <p className="text-xs text-gray-500 mt-2">
                  AI understands medical abbreviations: OD (once daily), BD (twice daily), TDS (three times), etc.
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-4 justify-center">
                <button
                  onClick={processPrescription}
                  disabled={processing || (!inputText && !selectedFile && !voiceTranscript)}
                  className="bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white font-semibold py-3 px-8 rounded-lg transition-colors flex items-center gap-2"
                >
                  {processing ? (
                    <>
                      <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                      Processing with Medical AI...
                    </>
                  ) : (
                    <>
                      🧠 Process with AI
                    </>
                  )}
                </button>
                <button
                  onClick={clearInput}
                  className="bg-gray-500 hover:bg-gray-600 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
                >
                  🗑️ Clear All
                </button>
              </div>

              {/* Processing Info */}
              {processing && (
                <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-blue-800 text-sm">
                    <strong>Advanced Processing:</strong> Using medical AI to analyze prescription, extract drug names, 
                    dosages, frequencies, and create optimal medication schedules...
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Medications Tab */}
        {activeTab === "medications" && (
          <div className="max-w-6xl mx-auto">
            <h2 className="text-2xl font-bold text-gray-800 mb-6 text-center">
              💊 Your Medication Schedule
            </h2>
            {medications.length === 0 ? (
              <div className="bg-white rounded-xl shadow-lg p-12 text-center">
                <div className="text-6xl mb-4">🏥</div>
                <p className="text-gray-500 text-lg">No medications found</p>
                <p className="text-gray-400 mt-2">Process a prescription to get started</p>
              </div>
            ) : (
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                {medications.map((medication) => (
                  <div
                    key={medication.id}
                    className="bg-white rounded-xl shadow-lg p-6 hover:shadow-xl transition-shadow medication-card"
                    style={{ borderTop: `4px solid ${medication.background_color}` }}
                  >
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div 
                          className="w-12 h-12 rounded-full flex items-center justify-center shadow-md"
                          style={{ backgroundColor: medication.background_color }}
                        >
                          <img 
                            src={medication.icon_svg} 
                            alt={medication.form}
                            className="w-6 h-6"
                            style={{ 
                              filter: `brightness(0) saturate(100%)`,
                              color: medication.medication_color
                            }}
                          />
                          <style jsx>{`
                            img[src="${medication.icon_svg}"] {
                              filter: brightness(0) saturate(100%) invert(${medication.medication_color === '#FFFFFF' ? '1' : '0'});
                            }
                          `}</style>
                        </div>
                        <div>
                          <h3 className="font-bold text-gray-800">{medication.medicine_name}</h3>
                          <p className="text-sm text-gray-500">{medication.display_name}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => deleteMedication(medication.id)}
                        className="text-red-500 hover:text-red-700 text-sm"
                      >
                        🗑️
                      </button>
                    </div>
                    
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-600">Dosage:</span>
                        <span className="text-sm text-gray-800">{medication.dosage}</span>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-600">Frequency:</span>
                        <span className="text-sm text-gray-800">{medication.frequency}x daily</span>
                      </div>
                      
                      <div>
                        <span className="text-sm font-medium text-gray-600">Times:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {medication.times.map((time, index) => (
                            <span
                              key={index}
                              className="text-xs px-2 py-1 rounded-full time-badge"
                              style={{ 
                                backgroundColor: `${medication.background_color}20`,
                                color: medication.background_color,
                                border: `1px solid ${medication.background_color}40`
                              }}
                            >
                              {formatTime(time)}
                            </span>
                          ))}
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-600">Duration:</span>
                        <span className="text-sm text-gray-800">{medication.course_duration_days} days</span>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-600">Start Date:</span>
                        <span className="text-sm text-gray-800">{medication.start_date}</span>
                      </div>
                    </div>
                    
                    <div className="mt-4 flex items-center gap-2">
                      <div 
                        className="h-2 rounded-full flex-1"
                        style={{ backgroundColor: medication.background_color }}
                      ></div>
                      <div 
                        className="w-8 h-8 rounded-full border-2 flex items-center justify-center"
                        style={{ 
                          borderColor: medication.background_color,
                          backgroundColor: medication.medication_color
                        }}
                      >
                        <div 
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: medication.medication_color }}
                        ></div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Results Tab */}
        {activeTab === "results" && processedResult && (
          <div className="max-w-4xl mx-auto">
            <div className="bg-white rounded-xl shadow-lg p-8">
              <h2 className="text-2xl font-bold text-gray-800 mb-6 text-center">
                ✅ AI Processing Results
              </h2>
              
              <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg success-border">
                <p className="text-green-800">
                  <strong>Success!</strong> Processed {processedResult.medications.length} medication(s) with medical AI.
                </p>
                <p className="text-green-600 text-sm mt-1">{processedResult.processing_notes}</p>
              </div>

              <div className="space-y-4">
                {processedResult.medications.map((medication, index) => (
                  <div
                    key={index}
                    className="border rounded-lg p-4 hover:bg-gray-50 transition-colors"
                    style={{ borderColor: medication.background_color, borderWidth: '2px' }}
                  >
                    <div className="flex items-center gap-3 mb-3">
                      <div 
                        className="w-10 h-10 rounded-full flex items-center justify-center shadow-sm"
                        style={{ backgroundColor: medication.background_color }}
                      >
                        <img 
                          src={medication.icon_svg} 
                          alt={medication.form}
                          className="w-5 h-5"
                          style={{ 
                            filter: medication.medication_color === '#FFFFFF' 
                              ? 'brightness(0) saturate(100%) invert(1)' 
                              : 'brightness(0) saturate(100%)'
                          }}
                        />
                      </div>
                      <div>
                        <h3 className="font-semibold text-gray-800">{medication.medicine_name}</h3>
                        <p className="text-sm text-gray-600">{medication.display_name}</p>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <span className="font-medium text-gray-600">Dosage:</span>
                        <p className="text-gray-800">{medication.dosage}</p>
                      </div>
                      <div>
                        <span className="font-medium text-gray-600">Frequency:</span>
                        <p className="text-gray-800">{medication.frequency}x daily</p>
                      </div>
                      <div>
                        <span className="font-medium text-gray-600">Duration:</span>
                        <p className="text-gray-800">{medication.course_duration_days} days</p>
                      </div>
                      <div>
                        <span className="font-medium text-gray-600">Start Date:</span>
                        <p className="text-gray-800">{medication.start_date}</p>
                      </div>
                    </div>
                    
                    <div className="mt-3">
                      <span className="font-medium text-gray-600 text-sm">Schedule:</span>
                      <div className="flex flex-wrap gap-2 mt-1">
                        {medication.times.map((time, timeIndex) => (
                          <span
                            key={timeIndex}
                            className="text-xs px-2 py-1 rounded-full time-badge"
                            style={{ 
                              backgroundColor: `${medication.background_color}20`,
                              color: medication.background_color,
                              border: `1px solid ${medication.background_color}40`
                            }}
                          >
                            {formatTime(time)}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              
              <div className="mt-6 p-4 bg-gray-50 rounded-lg">
                <p className="text-sm font-medium text-gray-700 mb-2">Raw Extracted Text:</p>
                <p className="text-sm text-gray-600">{processedResult.raw_text}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;