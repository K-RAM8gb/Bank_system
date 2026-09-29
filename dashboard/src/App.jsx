import { useState, useEffect } from 'react';
import { AlertCircle, CheckCircle, XCircle, Clock, Image as ImageIcon } from 'lucide-react';
import { format } from 'date-fns';

export default function App() {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);

  // Poll the backend every 5 seconds so new uploads appear automatically
  useEffect(() => {
    const fetchPayments = () => {
      fetch('http://127.0.0.1:8000/payments')
        .then(res => res.json())
        .then(data => {
          setPayments(data);
          setLoading(false);
        })
        .catch(err => console.error("Error fetching payments:", err));
    };

    fetchPayments();
    const interval = setInterval(fetchPayments, 5000);
    return () => clearInterval(interval);
  }, []);

  const getStatusConfig = (status) => {
    switch (status) {
      case 'APPROVED': return { color: 'text-green-700', bg: 'bg-green-50', border: 'border-green-200', icon: CheckCircle };
      case 'REJECTED': return { color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200', icon: XCircle };
      case 'NEEDS_VERIFICATION': return { color: 'text-yellow-700', bg: 'bg-yellow-50', border: 'border-yellow-200', icon: AlertCircle };
      default: return { color: 'text-gray-700', bg: 'bg-gray-50', border: 'border-gray-200', icon: Clock };
    }
  };

  if (loading) return <div className="p-8 text-center text-gray-500 font-medium">Loading payments...</div>;

  return (
    <div className="max-w-7xl mx-auto p-6 font-sans">
      <header className="mb-8">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">Payment Verification Dashboard</h1>
        <p className="text-gray-600 mt-2">Review system decisions, extracted data, and manual verification queues.</p>
      </header>

      <div className="space-y-8">
        {payments.map((payment) => {
          const StatusIcon = getStatusConfig(payment.verification_status).icon;
          const statusColors = getStatusConfig(payment.verification_status);

          return (
            <div key={payment.id} className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">

              {/* Header: Status & Reason */}
              <div className={`px-6 py-4 border-b ${statusColors.border} ${statusColors.bg} flex items-start justify-between`}>
                <div className="flex items-center space-x-3">
                  <StatusIcon className={`w-7 h-7 ${statusColors.color}`} />
                  <div>
                    <h2 className={`text-lg font-bold tracking-wide ${statusColors.color}`}>
                      {payment.verification_status.replace('_', ' ')}
                    </h2>
                    <p className="text-sm text-gray-700 mt-1 font-medium">{payment.reason}</p>
                  </div>
                </div>
                <div className="text-right text-sm text-gray-500 font-medium">
                  {format(new Date(payment.created_at), 'MMM dd, yyyy HH:mm')}
                </div>
              </div>

              {/* Body: Image + Comparison View */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-0">

                {/* Column 1: Submitted Image */}
                <div className="bg-gray-50 p-6 border-r border-gray-200 flex flex-col items-center justify-center min-h-[300px]">
                  <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 w-full text-left">Submitted Image</h3>
                  {payment.slip_image_url ? (
                    <a href={payment.slip_image_url} target="_blank" rel="noreferrer">
                      <img
                        src={payment.slip_image_url}
                        alt="Payment Slip"
                        className="max-h-72 w-auto object-contain rounded shadow-sm border border-gray-300 hover:opacity-90 transition-opacity cursor-pointer"
                      />
                    </a>
                  ) : (
                    <div className="text-gray-400 text-sm flex flex-col items-center">
                      <ImageIcon className="w-10 h-10 mb-2 opacity-30" />
                      No Image Saved
                    </div>
                  )}
                </div>

                {/* Columns 2 & 3: Data Comparison */}
                <div className="lg:col-span-2 p-6 grid grid-cols-1 md:grid-cols-2 gap-8">

                  {/* Order Details (Expected) */}
                  <div className="space-y-4">
                    <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider border-b border-gray-200 pb-2">
                      Customer Expected Details
                    </h3>
                    <div className="space-y-3 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-500">Order ID:</span>
                        <span className="font-mono text-gray-900 bg-gray-100 px-2 py-0.5 rounded">{payment.order_id.slice(0, 8)}...</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Customer Phone:</span>
                        <span className="font-medium text-gray-900">{payment.orders?.customer_phone}</span>
                      </div>
                      <div className="flex justify-between items-center bg-gray-50 p-2 rounded border border-gray-100 mt-2">
                        <span className="text-gray-600 font-medium">Expected Amount:</span>
                        <span className="font-bold text-lg text-gray-900">Rs. {payment.orders?.expected_amount}</span>
                      </div>
                    </div>
                  </div>

                  {/* System Conclusion (Extracted) */}
                  <div className="space-y-4">
                    <h3 className="text-xs font-bold text-blue-700 uppercase tracking-wider border-b border-blue-100 pb-2">
                      System Extracted Details
                    </h3>
                    <div className="space-y-3 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-500">Found Reference:</span>
                        <span className={`font-mono ${payment.extracted_reference ? 'text-gray-900' : 'text-gray-400'}`}>
                          {payment.extracted_reference || 'Not found'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Found Account:</span>
                        <span className={`font-mono ${payment.extracted_account !== 'XXXX1234' ? 'text-red-600 font-bold' : 'text-green-600'}`}>
                          {payment.extracted_account || 'Not found'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Found Date:</span>
                        <span className="text-gray-900 font-medium">{payment.extracted_date || 'Not found'}</span>
                      </div>

                      <div className={`flex justify-between items-center p-2 rounded border mt-2 ${payment.extracted_amount !== payment.orders?.expected_amount
                        ? 'bg-red-50 border-red-100'
                        : 'bg-green-50 border-green-100'
                        }`}>
                        <span className="text-gray-600 font-medium">Extracted Amount:</span>
                        <span className={`font-bold text-lg ${payment.extracted_amount !== payment.orders?.expected_amount ? 'text-red-700' : 'text-green-700'
                          }`}>
                          {payment.extracted_amount ? `Rs. ${payment.extracted_amount}` : 'Unreadable'}
                        </span>
                      </div>
                    </div>
                  </div>

                </div>
              </div>
            </div>
          );
        })}
        {payments.length === 0 && (
          <div className="text-center py-16 text-gray-500 bg-white rounded-xl shadow-sm border border-gray-200">
            No payments processed yet. Upload a slip via the API to see it here.
          </div>
        )}
      </div>
    </div>
  );
}