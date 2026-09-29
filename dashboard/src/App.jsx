import { useState, useEffect } from 'react';
import { AlertCircle, CheckCircle, XCircle, Clock } from 'lucide-react';
import { format } from 'date-fns';

export default function App() {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://127.0.0.1:8000/payments')
      .then(res => res.json())
      .then(data => {
        setPayments(data);
        setLoading(false);
      })
      .catch(err => console.error("Error fetching payments:", err));
  }, []);

  const getStatusConfig = (status) => {
    switch (status) {
      case 'APPROVED': return { color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle };
      case 'REJECTED': return { color: 'text-red-600', bg: 'bg-red-100', icon: XCircle };
      case 'NEEDS_VERIFICATION': return { color: 'text-yellow-600', bg: 'bg-yellow-100', icon: AlertCircle };
      default: return { color: 'text-gray-600', bg: 'bg-gray-100', icon: Clock };
    }
  };

  if (loading) return <div className="p-8 text-center text-gray-500">Loading payments...</div>;

  return (
    <div className="max-w-6xl mx-auto p-6">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Payment Verification Dashboard</h1>
        <p className="text-gray-600">Review system decisions and manual verification queues.</p>
      </header>

      <div className="space-y-6">
        {payments.map((payment) => {
          const StatusIcon = getStatusConfig(payment.verification_status).icon;
          const statusColors = getStatusConfig(payment.verification_status);

          return (
            <div key={payment.id} className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">

              {/* Header: Status & Reason */}
              <div className={`px-6 py-4 border-b border-gray-200 ${statusColors.bg} flex items-start justify-between`}>
                <div className="flex items-center space-x-3">
                  <StatusIcon className={`w-6 h-6 ${statusColors.color}`} />
                  <div>
                    <h2 className={`text-lg font-bold ${statusColors.color}`}>
                      {payment.verification_status.replace('_', ' ')}
                    </h2>
                    <p className="text-sm text-gray-700 mt-1 font-medium">{payment.reason}</p>
                  </div>
                </div>
                <div className="text-right text-sm text-gray-500">
                  {format(new Date(payment.created_at), 'MMM dd, yyyy HH:mm')}
                </div>
              </div>

              {/* Body: Comparison View */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-6">

                {/* Column 1: Order Details (Expected) */}
                <div className="bg-gray-50 p-4 rounded-md border border-gray-100">
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-4">Customer Expected Details</h3>
                  <div className="space-y-3 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Order ID:</span>
                      <span className="font-mono text-gray-900">{payment.order_id.slice(0, 8)}...</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Customer:</span>
                      <span className="font-medium text-gray-900">{payment.orders?.customer_phone}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Expected Amount:</span>
                      <span className="font-bold text-gray-900">Rs. {payment.orders?.expected_amount}</span>
                    </div>
                  </div>
                </div>

                {/* Column 2: System Conclusion (Extracted) */}
                <div className="bg-blue-50 p-4 rounded-md border border-blue-100">
                  <h3 className="text-xs font-bold text-blue-800 uppercase tracking-wider mb-4">System Extracted Details</h3>
                  <div className="space-y-3 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Extracted Amount:</span>
                      <span className={`font-bold ${payment.extracted_amount !== payment.orders?.expected_amount ? 'text-red-600' : 'text-green-600'}`}>
                        {payment.extracted_amount ? `Rs. ${payment.extracted_amount}` : 'Unreadable'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Found Reference:</span>
                      <span className="font-mono text-gray-900">{payment.extracted_reference || 'None'}</span>
                    </div>
                    <div className="flex justify-between mt-4 pt-4 border-t border-blue-200">
                      <span className="text-gray-500">Image Hash:</span>
                      <span className="font-mono text-xs text-gray-400 truncate max-w-[150px]">{payment.image_hash}</span>
                    </div>
                  </div>
                </div>

              </div>
            </div>
          );
        })}
        {payments.length === 0 && (
          <div className="text-center py-12 text-gray-500 bg-white rounded-lg shadow">
            No payments processed yet. Upload a slip to see it here.
          </div>
        )}
      </div>
    </div>
  );
}