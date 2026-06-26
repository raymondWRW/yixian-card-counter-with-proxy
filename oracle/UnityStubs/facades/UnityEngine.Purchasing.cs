// UnityEngine.Purchasing facade
using System;
namespace UnityEngine.Purchasing
{
    public interface IStoreListener { void OnInitialized(IStoreController c, IExtensionProvider e); void OnInitializeFailed(InitializationFailureReason r); PurchaseProcessingResult ProcessPurchase(PurchaseEventArgs e); void OnPurchaseFailed(Product p, PurchaseFailureReason r); }
    public interface IStoreController { ProductCollection products { get; } void InitiatePurchase(Product p); void InitiatePurchase(string id); void ConfirmPendingPurchase(Product p); }
    public interface IExtensionProvider { T GetExtension<T>() where T : IStoreExtension; }
    public interface IStoreExtension { }
    public class Product { public ProductDefinition definition { get; set; } public ProductMetadata metadata { get; set; } public string transactionID { get; set; } public string receipt { get; set; } public bool hasReceipt => !string.IsNullOrEmpty(receipt); public bool availableToPurchase => true; }
    public class ProductDefinition { public string id { get; set; } public string storeSpecificId { get; set; } public ProductType type { get; set; } public ProductDefinition(string i, ProductType t) { id = i; storeSpecificId = i; type = t; } }
    public class ProductMetadata { public string localizedTitle { get; set; } public string localizedDescription { get; set; } public string isoCurrencyCode { get; set; } public decimal localizedPrice { get; set; } public string localizedPriceString { get; set; } }
    public class ProductCollection { public Product[] all => new Product[0]; public Product WithID(string i) => null; public Product WithStoreSpecificID(string i) => null; }
    public class PurchaseEventArgs { public Product purchasedProduct { get; set; } }
    public class ConfigurationBuilder { public static ConfigurationBuilder Instance(params IPurchasingModule[] m) => new ConfigurationBuilder(); public ConfigurationBuilder AddProduct(string i, ProductType t) => this; }
    public interface IPurchasingModule { }
    public static class UnityPurchasing { public static void Initialize(IStoreListener l, ConfigurationBuilder b) { } }
    public static class StandardPurchasingModule { public static IPurchasingModule Instance() => null; }
    public enum ProductType { Consumable, NonConsumable, Subscription }
    public enum PurchaseProcessingResult { Complete, Pending }
    public enum PurchaseFailureReason { PurchasingUnavailable, ExistingPurchasePending, ProductUnavailable, SignatureInvalid, UserCancelled, PaymentDeclined, DuplicateTransaction, Unknown }
    public enum InitializationFailureReason { PurchasingUnavailable, NoProductsAvailable, AppNotKnown }
    public interface IDetailedStoreListener : IStoreListener { void OnPurchaseFailed(Product p, PurchaseFailureDescription d); }
    public class PurchaseFailureDescription { public string productId { get; set; } public PurchaseFailureReason reason { get; set; } public string message { get; set; } }
}
