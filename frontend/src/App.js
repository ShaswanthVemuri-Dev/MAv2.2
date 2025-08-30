import React, { useState, useEffect } from "react";
import "./App.css";
import axios from "axios";

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

  useEffect(() => {
    fetchMedications();
  }, []);

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
    if (!inputText && !selectedFile) {
      alert("Please provide either text or upload an image");
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
            🏥 Smart Prescription Processor
          </h1>
          <p className="text-gray-600">
            Upload prescription images or enter text to get organized medication schedules
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
                📄 Upload or Enter Prescription
              </h2>
              
              {/* Image Upload Section */}
              <div className="mb-8">
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  📷 Upload Prescription Image
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
                        <p className="text-sm text-gray-500">PNG, JPG up to 10MB</p>
                      </div>
                    )}
                  </label>
                </div>
              </div>

              {/* Divider */}
              <div className="flex items-center my-8">
                <div className="flex-1 border-t border-gray-300"></div>
                <span className="px-4 text-gray-500 font-medium">OR</span>
                <div className="flex-1 border-t border-gray-300"></div>
              </div>

              {/* Text Input Section */}
              <div className="mb-8">
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  ✏️ Enter Prescription Text
                </label>
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  className="w-full h-32 p-4 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Enter prescription details like:&#10;Dolo 650 - 1 tablet - 3 times daily - 5 days&#10;Amoxicillin 500mg - 1 capsule - twice daily - 7 days"
                />
              </div>

              {/* Action Buttons */}
              <div className="flex gap-4 justify-center">
                <button
                  onClick={processPrescription}
                  disabled={processing || (!inputText && !selectedFile)}
                  className="bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white font-semibold py-3 px-8 rounded-lg transition-colors flex items-center gap-2"
                >
                  {processing ? (
                    <>
                      <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                      Processing...
                    </>
                  ) : (
                    <>
                      🔄 Process Prescription
                    </>
                  )}
                </button>
                <button
                  onClick={clearInput}
                  className="bg-gray-500 hover:bg-gray-600 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
                >
                  🗑️ Clear
                </button>
              </div>
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
                    className="bg-white rounded-xl shadow-lg p-6 hover:shadow-xl transition-shadow"
                  >
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div className="text-3xl">{medication.icon}</div>
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
                              className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full"
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
                    
                    <div
                      className="mt-4 h-2 rounded-full"
                      style={{ backgroundColor: medication.color }}
                    ></div>
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
                ✅ Processing Results
              </h2>
              
              <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
                <p className="text-green-800">
                  <strong>Success!</strong> Processed {processedResult.medications.length} medication(s) from your prescription.
                </p>
                <p className="text-green-600 text-sm mt-1">{processedResult.processing_notes}</p>
              </div>

              <div className="space-y-4">
                {processedResult.medications.map((medication, index) => (
                  <div
                    key={index}
                    className="border border-gray-200 rounded-lg p-4 hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-2xl">{medication.icon}</span>
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
                            className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full"
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